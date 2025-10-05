use std::collections::{HashMap, VecDeque};
use std::str::FromStr;

use chrono::{DateTime, Duration, NaiveDateTime, SecondsFormat, Utc};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList};
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(FromPyObject)]
struct TradeInput {
    timestamp_us: i64,
    side: String,
    price: String,
    size: String,
    post_only: bool,
}

#[derive(FromPyObject, Clone)]
struct IntervalSpec {
    key: String,
    label: String,
    delta_seconds: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct RawOrder {
    #[serde(default)]
    order_id: Option<String>,
    #[serde(default)]
    status: Option<String>,
    #[serde(default, rename = "order_status")]
    legacy_status: Option<String>,
    #[serde(default)]
    client_order_id: Option<String>,
    #[serde(default)]
    side: Option<String>,
    #[serde(default)]
    completed_time: Option<String>,
    #[serde(default)]
    expire_time: Option<String>,
    #[serde(default)]
    submitted_time: Option<String>,
    #[serde(default)]
    created_time: Option<String>,
    #[serde(default)]
    order_placed_time: Option<String>,
    #[serde(default)]
    last_fill_time: Option<String>,
    #[serde(default)]
    average_filled_price: Option<String>,
    #[serde(default)]
    product_id: Option<String>,
    #[serde(default)]
    order_configuration: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct RawFill {
    #[serde(default)]
    order_id: Option<String>,
    #[serde(default)]
    trade_time: Option<String>,
    #[serde(default)]
    size: Option<Value>,
    #[serde(default)]
    base_size: Option<Value>,
    #[serde(default)]
    price: Option<Value>,
    #[serde(default)]
    unit_price: Option<Value>,
    #[serde(default)]
    average_price: Option<Value>,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Side {
    Buy,
    Sell,
}

impl TryFrom<&str> for Side {
    type Error = PyErr;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        match value.to_ascii_uppercase().as_str() {
            "BUY" => Ok(Side::Buy),
            "SELL" => Ok(Side::Sell),
            other => Err(PyValueError::new_err(format!("unknown side: {}", other))),
        }
    }
}

struct Trade {
    timestamp: DateTime<Utc>,
    side: Side,
    price: Decimal,
    size: Decimal,
    post_only: bool,
}

#[derive(Clone, Copy)]
struct Lot {
    price: Decimal,
    size: Decimal,
}

struct Entry {
    timestamp: DateTime<Utc>,
    realized_profit: Decimal,
    maker_volume: Decimal,
    taker_volume: Decimal,
    fee: Decimal,
}

struct RawMetrics {
    profit_before_fees: Decimal,
    maker_volume: Decimal,
    taker_volume: Decimal,
    fee_total: Decimal,
    profit_after_fees: Decimal,
}

fn timestamp_us_to_datetime(ts: i64) -> PyResult<DateTime<Utc>> {
    let secs = ts.div_euclid(1_000_000);
    let micros = ts.rem_euclid(1_000_000) as u32;
    let nanos = micros * 1_000;
    let naive = NaiveDateTime::from_timestamp_opt(secs, nanos)
        .ok_or_else(|| PyValueError::new_err("timestamp out of range"))?;
    Ok(DateTime::<Utc>::from_utc(naive, Utc))
}

fn parse_decimal(value: &str, label: &str) -> PyResult<Decimal> {
    Decimal::from_str(value)
        .map_err(|_| PyValueError::new_err(format!("invalid decimal for {}: {}", label, value)))
}

fn build_entries(trades: &[Trade], maker_fee: Decimal, taker_fee: Decimal) -> Vec<Entry> {
    let mut long_lots: VecDeque<Lot> = VecDeque::new();
    let mut short_lots: VecDeque<Lot> = VecDeque::new();
    let mut entries: Vec<Entry> = Vec::with_capacity(trades.len());
    let zero = Decimal::ZERO;

    for trade in trades {
        let mut remaining = trade.size;
        let mut realized = Decimal::ZERO;

        match trade.side {
            Side::Buy => {
                while remaining > zero {
                    if let Some(front) = short_lots.front_mut() {
                        let matched = if remaining <= front.size { remaining } else { front.size };
                        realized += (front.price - trade.price) * matched;
                        front.size -= matched;
                        remaining -= matched;
                        if front.size <= zero {
                            short_lots.pop_front();
                        }
                    } else {
                        break;
                    }
                }
                if remaining > zero {
                    long_lots.push_back(Lot {
                        price: trade.price,
                        size: remaining,
                    });
                }
            }
            Side::Sell => {
                while remaining > zero {
                    if let Some(front) = long_lots.front_mut() {
                        let matched = if remaining <= front.size { remaining } else { front.size };
                        realized += (trade.price - front.price) * matched;
                        front.size -= matched;
                        remaining -= matched;
                        if front.size <= zero {
                            long_lots.pop_front();
                        }
                    } else {
                        break;
                    }
                }
                if remaining > zero {
                    short_lots.push_back(Lot {
                        price: trade.price,
                        size: remaining,
                    });
                }
            }
        }

        let notional = trade.price * trade.size;
        let maker_volume = if trade.post_only { notional } else { zero };
        let taker_volume = if trade.post_only { zero } else { notional };
        let fee_rate = if trade.post_only { maker_fee } else { taker_fee };
        let fee = notional * fee_rate;

        entries.push(Entry {
            timestamp: trade.timestamp,
            realized_profit: realized,
            maker_volume,
            taker_volume,
            fee,
        });
    }

    entries
}

fn summarise_interval(entries: &[Entry], start: DateTime<Utc>) -> RawMetrics {
    let zero = Decimal::ZERO;
    let mut profit_before = zero;
    let mut maker_volume = zero;
    let mut taker_volume = zero;
    let mut fee_total = zero;

    for entry in entries {
        if entry.timestamp < start {
            continue;
        }
        profit_before += entry.realized_profit;
        maker_volume += entry.maker_volume;
        taker_volume += entry.taker_volume;
        fee_total += entry.fee;
    }

    let profit_after = profit_before - fee_total;
    RawMetrics {
        profit_before_fees: profit_before,
        maker_volume,
        taker_volume,
        fee_total,
        profit_after_fees: profit_after,
    }
}

fn interval_start(now: DateTime<Utc>, delta: Option<i64>, cutoff: DateTime<Utc>) -> DateTime<Utc> {
    match delta {
        None => cutoff,
        Some(seconds) => {
            let start = now - Duration::seconds(seconds.max(0));
            if start < cutoff { cutoff } else { start }
        }
    }
}

#[pyfunction]
fn summarise_trades(
    py: Python<'_>,
    trades: Vec<TradeInput>,
    intervals: Vec<IntervalSpec>,
    now_timestamp_us: i64,
    cutoff_timestamp_us: i64,
    maker_fee_rate: &str,
    taker_fee_rate: &str,
) -> PyResult<PyObject> {
    let maker_fee = parse_decimal(maker_fee_rate, "maker_fee_rate")?;
    let taker_fee = parse_decimal(taker_fee_rate, "taker_fee_rate")?;
    let now = timestamp_us_to_datetime(now_timestamp_us)?;
    let cutoff = timestamp_us_to_datetime(cutoff_timestamp_us)?;

    let mut parsed_trades: Vec<Trade> = Vec::with_capacity(trades.len());
    for trade in trades {
        let price = parse_decimal(&trade.price, "price")?;
        let size = parse_decimal(&trade.size, "size")?;
        if size <= Decimal::ZERO || price <= Decimal::ZERO {
            continue;
        }
        let timestamp = timestamp_us_to_datetime(trade.timestamp_us)?;
        if timestamp < cutoff {
            continue;
        }
        let side = Side::try_from(trade.side.as_str())?;
        parsed_trades.push(Trade {
            timestamp,
            side,
            price,
            size,
            post_only: trade.post_only,
        });
    }

    parsed_trades.sort_by_key(|trade| trade.timestamp);
    let entries = build_entries(&parsed_trades, maker_fee, taker_fee);

    let mut intervals_py = Vec::with_capacity(intervals.len());
    let mut total_before = Decimal::ZERO;
    let mut total_after = Decimal::ZERO;

    for spec in &intervals {
        let start = interval_start(now, spec.delta_seconds, cutoff);
        let metrics = summarise_interval(&entries, start);
        let interval_dict = PyDict::new(py);
        interval_dict.set_item("key", &spec.key)?;
        interval_dict.set_item("label", &spec.label)?;
        interval_dict.set_item("profit_before_fees", metrics.profit_before_fees.to_string())?;
        interval_dict.set_item("maker_volume", metrics.maker_volume.to_string())?;
        interval_dict.set_item("taker_volume", metrics.taker_volume.to_string())?;
        interval_dict.set_item("fee_total", metrics.fee_total.to_string())?;
        interval_dict.set_item("profit_after_fees", metrics.profit_after_fees.to_string())?;

        if spec.key == "all" {
            total_before = metrics.profit_before_fees;
            total_after = metrics.profit_after_fees;
        }

        intervals_py.push(interval_dict);
    }

    let result = PyDict::new(py);
    result.set_item("intervals", PyList::new(py, intervals_py))?;
    result.set_item("total_profit_before_fees", total_before.to_string())?;
    result.set_item("total_profit_after_fees", total_after.to_string())?;

    Ok(result.into())
}

fn value_to_string(value: &Value) -> Option<String> {
    match value {
        Value::String(s) => Some(s.clone()),
        Value::Number(n) => Some(n.to_string()),
        Value::Bool(b) => Some(b.to_string()),
        _ => None,
    }
}

fn option_to_string(value: Option<&Value>) -> Option<String> {
    value.and_then(value_to_string)
}

fn decimal_from_value(value: Option<&Value>) -> Option<Decimal> {
    option_to_string(value).and_then(|text| Decimal::from_str(text.trim()).ok())
}

fn parse_datetime_text(text: &str) -> Option<DateTime<Utc>> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return None;
    }
    if let Ok(dt) = DateTime::parse_from_rfc3339(trimmed) {
        return Some(dt.with_timezone(&Utc));
    }
    if let Ok(dt) = NaiveDateTime::parse_from_str(trimmed, "%Y-%m-%dT%H:%M:%S%.f") {
        return Some(DateTime::<Utc>::from_utc(dt, Utc));
    }
    if let Ok(dt) = NaiveDateTime::parse_from_str(trimmed, "%Y-%m-%d %H:%M:%S%.f") {
        return Some(DateTime::<Utc>::from_utc(dt, Utc));
    }
    None
}

fn parse_datetime_value(value: Option<&Value>) -> Option<DateTime<Utc>> {
    option_to_string(value)
        .as_deref()
        .and_then(|s| if s.is_empty() { None } else { parse_datetime_text(s) })
}

fn format_datetime(dt: DateTime<Utc>) -> String {
    dt.to_rfc3339_opts(SecondsFormat::Millis, true)
}

fn parse_boolish(value: Option<&Value>) -> Option<bool> {
    match value {
        Some(Value::Bool(b)) => Some(*b),
        Some(other) => option_to_string(Some(other)).as_deref().and_then(|s| {
            let lower = s.trim().to_ascii_lowercase();
            match lower.as_str() {
                "true" => Some(true),
                "false" => Some(false),
                _ => None,
            }
        }),
        None => None,
    }
}

#[derive(Clone, Copy)]
struct FillData {
    size: Decimal,
    price: Decimal,
    trade_time: Option<DateTime<Utc>>,
}

fn collect_fills(fills: &[RawFill]) -> HashMap<String, Vec<FillData>> {
    let mut map: HashMap<String, Vec<FillData>> = HashMap::new();
    for fill in fills {
        let Some(order_id) = fill
            .order_id
            .as_ref()
            .and_then(|s| if s.is_empty() { None } else { Some(s.clone()) })
        else {
            continue;
        };
        let size = decimal_from_value(fill.size.as_ref())
            .or_else(|| decimal_from_value(fill.base_size.as_ref()));
        let price = decimal_from_value(fill.price.as_ref())
            .or_else(|| decimal_from_value(fill.unit_price.as_ref()))
            .or_else(|| decimal_from_value(fill.average_price.as_ref()));
        let (Some(size), Some(price)) = (size, price) else { continue; };
        if size <= Decimal::ZERO || price <= Decimal::ZERO {
            continue;
        }
        let trade_time = fill
            .trade_time
            .as_deref()
            .and_then(parse_datetime_text);
        map.entry(order_id)
            .or_default()
            .push(FillData { size, price, trade_time });
    }
    map
}

enum OrderConfigType {
    Limit,
    StopLimit,
    TriggerBracket,
    Market,
    Unknown,
}

fn extract_order_config<'a>(value: Option<&'a Value>) -> (OrderConfigType, Option<&'a serde_json::Map<String, Value>>) {
    let Some(container) = value.and_then(|v| v.as_object()) else {
        return (OrderConfigType::Unknown, None);
    };

    for key in ["limit_limit_gtd", "limit_limit_gtc"] {
        if let Some(entry) = container.get(key).and_then(|v| v.as_object()) {
            return (OrderConfigType::Limit, Some(entry));
        }
    }

    for key in ["stop_limit_stop_limit_gtd", "stop_limit_stop_limit_gtc"] {
        if let Some(entry) = container.get(key).and_then(|v| v.as_object()) {
            return (OrderConfigType::StopLimit, Some(entry));
        }
    }

    for key in ["trigger_bracket_gtd", "trigger_bracket_gtc"] {
        if let Some(entry) = container.get(key).and_then(|v| v.as_object()) {
            return (OrderConfigType::TriggerBracket, Some(entry));
        }
    }

    for key in ["market_market_ioc", "market_market_gtc"] {
        if let Some(entry) = container.get(key).and_then(|v| v.as_object()) {
            return (OrderConfigType::Market, Some(entry));
        }
    }

    (OrderConfigType::Unknown, None)
}

fn min_datetime(values: &[Option<DateTime<Utc>>]) -> Option<DateTime<Utc>> {
    values.iter().filter_map(|opt| *opt).min()
}

fn resolve_submitted_time(
    order: &RawOrder,
    fills: Option<&Vec<FillData>>,
    completed: Option<DateTime<Utc>>,
) -> (DateTime<Utc>, bool) {
    let candidates = [
        order.submitted_time.as_deref(),
        order.created_time.as_deref(),
        order.order_placed_time.as_deref(),
        order.last_fill_time.as_deref(),
    ];

    for candidate in candidates.iter().flatten() {
        if let Some(dt) = parse_datetime_text(candidate) {
            return (dt, false);
        }
    }

    if let Some(fills_vec) = fills {
        let fill_times: Vec<Option<DateTime<Utc>>> = fills_vec.iter().map(|fill| fill.trade_time).collect();
        if let Some(min_dt) = min_datetime(&fill_times) {
            return (min_dt, false);
        }
    }

    if let Some(dt) = completed {
        return (dt, false);
    }

    (Utc::now(), true)
}

fn average_fill_price(fills: Option<&Vec<FillData>>) -> Option<Decimal> {
    let fills_vec = fills?;
    let mut total_size = Decimal::ZERO;
    let mut total_value = Decimal::ZERO;
    for fill in fills_vec {
        if fill.size <= Decimal::ZERO || fill.price <= Decimal::ZERO {
            continue;
        }
        total_size += fill.size;
        total_value += fill.size * fill.price;
    }
    if total_size > Decimal::ZERO && total_value > Decimal::ZERO {
        Some(total_value / total_size)
    } else {
        None
    }
}

struct ProcessedOpenRecord {
    order_id: String,
    side: String,
    limit_price: Decimal,
    base_size: Decimal,
    status: String,
    client_order_id: String,
    end_time: Option<DateTime<Utc>>,
    product_id: String,
    stop_price: Option<Decimal>,
}

struct ProcessedExecutedRecord {
    order_id: String,
    ts_submitted: DateTime<Utc>,
    ts_submitted_inferred: bool,
    ts_filled: Option<DateTime<Utc>>,
    side: String,
    limit_price: Decimal,
    base_size: Decimal,
    status: String,
    filled_size: Option<Decimal>,
    client_order_id: String,
    end_time: Option<DateTime<Utc>>,
    product_id: String,
    stop_price: Option<Decimal>,
    post_only: bool,
}

fn process_orders_internal(
    orders: &[RawOrder],
    fills: &[RawFill],
    default_product_id: &str,
) -> Result<(Vec<ProcessedOpenRecord>, Vec<ProcessedExecutedRecord>), String> {
    let fills_by_order = collect_fills(fills);
    let mut open_records: Vec<ProcessedOpenRecord> = Vec::new();
    let mut executed_records: Vec<ProcessedExecutedRecord> = Vec::new();

    for order in orders {
        let Some(order_id) = order
            .order_id
            .as_ref()
            .and_then(|s| if s.is_empty() { None } else { Some(s.clone()) })
        else {
            continue;
        };

        let status = order
            .status
            .as_ref()
            .or(order.legacy_status.as_ref())
            .map(|s| s.to_ascii_uppercase())
            .unwrap_or_else(|| "NEW".to_string());

        let (config_type, config_opt) = extract_order_config(order.order_configuration.as_ref());
        let Some(config) = config_opt else {
            continue;
        };

        let client_order_id = order.client_order_id.clone().unwrap_or_default();
        let side_text = order.side.clone().unwrap_or_else(|| "BUY".to_string());
        let side_enum = Side::try_from(side_text.as_str()).unwrap_or(Side::Buy);
        let side_str = match side_enum {
            Side::Buy => "BUY".to_string(),
            Side::Sell => "SELL".to_string(),
        };

        let fills_vec = fills_by_order.get(&order_id);
        let filled_size = fills_vec.map(|vec| {
            vec.iter().fold(Decimal::ZERO, |acc, fill| acc + fill.size)
        }).filter(|total| *total > Decimal::ZERO);

        let mut completed_time = if status != "OPEN" {
            order
                .completed_time
                .as_deref()
                .and_then(parse_datetime_text)
        } else {
            None
        };
        if completed_time.is_none() {
            if let Some(fills_vec) = fills_vec {
                completed_time = fills_vec
                    .iter()
                    .filter_map(|fill| fill.trade_time)
                    .last();
            }
        }

        let (submitted_time, submitted_inferred) =
            resolve_submitted_time(order, fills_vec, completed_time);

        let mut base_size = decimal_from_value(config.get("base_size"))
            .or_else(|| decimal_from_value(config.get("base_order_size")))
            .unwrap_or_else(|| Decimal::ZERO);
        if (base_size == Decimal::ZERO || base_size.is_zero())
            && filled_size.is_some()
        {
            base_size = filled_size.unwrap();
        }

        let order_avg_price = order
            .average_filled_price
            .as_ref()
            .and_then(|text| Decimal::from_str(text.trim()).ok());

        let product_id = order
            .product_id
            .as_ref()
            .and_then(|s| if s.is_empty() { None } else { Some(s.clone()) })
            .unwrap_or_else(|| default_product_id.to_string());

        let expire_time = order
            .expire_time
            .as_deref()
            .and_then(parse_datetime_text);

        let (limit_price, stop_price, end_time, post_only_flag) = match config_type {
            OrderConfigType::Market => {
                let limit_price = average_fill_price(fills_vec)
                    .or(order_avg_price)
                    .unwrap_or_else(|| Decimal::ZERO);
                let end_time = completed_time.or(Some(submitted_time));
                (limit_price, None, end_time, false)
            }
            OrderConfigType::TriggerBracket => {
                let limit_price = decimal_from_value(config.get("limit_price"))
                    .unwrap_or_else(|| Decimal::ZERO);
                let stop_price = decimal_from_value(config.get("stop_trigger_price"))
                    .or_else(|| decimal_from_value(config.get("stop_price")));
                let end_time = parse_datetime_value(config.get("end_time"))
                    .or(expire_time)
                    .or(Some(submitted_time));
                (limit_price, stop_price, end_time, false)
            }
            OrderConfigType::StopLimit => {
                let limit_price = decimal_from_value(config.get("limit_price"))
                    .unwrap_or_else(|| Decimal::ZERO);
                let stop_price = decimal_from_value(config.get("stop_price"));
                let end_time = parse_datetime_value(config.get("end_time"))
                    .or(expire_time)
                    .or(Some(submitted_time));
                (limit_price, stop_price, end_time, false)
            }
            OrderConfigType::Limit => {
                let limit_price = decimal_from_value(config.get("limit_price"))
                    .unwrap_or_else(|| Decimal::ZERO);
                let raw_post_only = parse_boolish(config.get("post_only"));
                let post_only = raw_post_only.unwrap_or(false);
                let end_time = parse_datetime_value(config.get("end_time"))
                    .or(expire_time)
                    .or(Some(submitted_time));
                (limit_price, None, end_time, post_only)
            }
            OrderConfigType::Unknown => continue,
        };

        if status == "OPEN" {
            open_records.push(ProcessedOpenRecord {
                order_id: order_id.clone(),
                side: side_str.clone(),
                limit_price,
                base_size,
                status: status.clone(),
                client_order_id: client_order_id.clone(),
                end_time,
                product_id: product_id.clone(),
                stop_price,
            });
        }

        executed_records.push(ProcessedExecutedRecord {
            order_id,
            ts_submitted: submitted_time,
            ts_submitted_inferred: submitted_inferred,
            ts_filled: completed_time,
            side: side_str,
            limit_price,
            base_size,
            status,
            filled_size,
            client_order_id,
            end_time,
            product_id,
            stop_price,
            post_only: matches!(config_type, OrderConfigType::Limit) && post_only_flag,
        });
    }

    Ok((open_records, executed_records))
}

#[pyfunction]
fn process_orders_and_fills(
    py: Python<'_>,
    orders: &PyAny,
    fills: &PyAny,
    product_id: &str,
) -> PyResult<PyObject> {
    let json = py.import("json")?;
    let orders_json: String = json.call_method1("dumps", (orders,))?.extract()?;
    let fills_json: String = json.call_method1("dumps", (fills,))?.extract()?;

    let orders: Vec<RawOrder> = serde_json::from_str(&orders_json)
        .map_err(|err| PyValueError::new_err(format!("Failed to parse orders payload: {err}")))?;
    let fills: Vec<RawFill> = serde_json::from_str(&fills_json)
        .map_err(|err| PyValueError::new_err(format!("Failed to parse fills payload: {err}")))?;

    match process_orders_internal(&orders, &fills, product_id) {
        Ok((open_records, executed_records)) => {
            let open_list = PyList::empty(py);
            for record in open_records {
                let dict = PyDict::new(py);
                dict.set_item("order_id", record.order_id)?;
                dict.set_item("side", record.side)?;
                dict.set_item("limit_price", record.limit_price.to_string())?;
                dict.set_item("base_size", record.base_size.to_string())?;
                dict.set_item("status", record.status)?;
                dict.set_item("client_order_id", record.client_order_id)?;
                dict.set_item("end_time", record.end_time.map(format_datetime))?;
                dict.set_item("product_id", record.product_id)?;
                dict.set_item(
                    "stop_price",
                    record.stop_price.map(|d| d.to_string()),
                )?;
                open_list.append(dict)?;
            }

            let executed_list = PyList::empty(py);
            for record in executed_records {
                let dict = PyDict::new(py);
                dict.set_item("order_id", record.order_id)?;
                dict.set_item("ts_submitted", format_datetime(record.ts_submitted))?;
                dict.set_item("ts_submitted_inferred", record.ts_submitted_inferred)?;
                dict.set_item("ts_filled", record.ts_filled.map(format_datetime))?;
                dict.set_item("side", record.side)?;
                dict.set_item("limit_price", record.limit_price.to_string())?;
                dict.set_item("base_size", record.base_size.to_string())?;
                dict.set_item("status", record.status)?;
                dict.set_item(
                    "filled_size",
                    record.filled_size.map(|d| d.to_string()),
                )?;
                dict.set_item("client_order_id", record.client_order_id)?;
                dict.set_item("end_time", record.end_time.map(format_datetime))?;
                dict.set_item("product_id", record.product_id)?;
                dict.set_item(
                    "stop_price",
                    record.stop_price.map(|d| d.to_string()),
                )?;
                dict.set_item("post_only", record.post_only)?;
                executed_list.append(dict)?;
            }

            let result = PyDict::new(py);
            result.set_item("open_records", open_list)?;
            result.set_item("executed_records", executed_list)?;
            Ok(result.into())
        }
        Err(message) => Err(PyValueError::new_err(message)),
    }
}

#[pymodule]
fn _pnl_rs(py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(summarise_trades, m)?)?;
    m.add_function(wrap_pyfunction!(process_orders_and_fills, m)?)?;
    // Ensure module has a __doc__ to aid debugging when import succeeds
    m.add("__doc__", "Rust-accelerated PnL helpers")?;
    Ok(())
}
