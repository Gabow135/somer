use pyo3::prelude::*;
use pyo3::exceptions::PyRuntimeError;
use redis::{Commands, Client, Connection};
use serde::{Deserialize, Serialize};
use std::sync::Mutex;

/// Represents a task in the queue.
#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
struct TaskItem {
    #[pyo3(get, set)]
    id: String,
    #[pyo3(get, set)]
    title: String,
    #[pyo3(get, set)]
    description: String,
    #[pyo3(get, set)]
    status: String,
    #[pyo3(get, set)]
    priority: u8,
    #[pyo3(get, set)]
    created_at: f64,
    #[pyo3(get, set)]
    started_at: Option<f64>,
    #[pyo3(get, set)]
    completed_at: Option<f64>,
    #[pyo3(get, set)]
    result: Option<String>,
    #[pyo3(get, set)]
    error: Option<String>,
    #[pyo3(get, set)]
    channel: String,
    #[pyo3(get, set)]
    user_id: String,
    #[pyo3(get, set)]
    session_id: String,
    #[pyo3(get, set)]
    retries: u8,
    #[pyo3(get, set)]
    max_retries: u8,
    #[pyo3(get, set)]
    task_type: String,
    #[pyo3(get, set)]
    payload: String,
}

#[pymethods]
impl TaskItem {
    #[new]
    fn new() -> Self {
        let now = chrono::Utc::now().timestamp_millis() as f64 / 1000.0;
        TaskItem {
            id: uuid::Uuid::new_v4().to_string(),
            title: String::new(),
            description: String::new(),
            status: "pending".to_string(),
            priority: 5,
            created_at: now,
            started_at: None,
            completed_at: None,
            result: None,
            error: None,
            channel: String::new(),
            user_id: String::new(),
            session_id: String::new(),
            retries: 0,
            max_retries: 3,
            task_type: "custom".to_string(),
            payload: "{}".to_string(),
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "TaskItem(id={}, title={}, status={}, priority={})",
            self.id, self.title, self.status, self.priority
        )
    }
}

impl TaskItem {
    /// Convert to Redis hash fields.
    fn to_hash_fields(&self) -> Vec<(String, String)> {
        let mut fields = vec![
            ("id".into(), self.id.clone()),
            ("title".into(), self.title.clone()),
            ("description".into(), self.description.clone()),
            ("status".into(), self.status.clone()),
            ("priority".into(), self.priority.to_string()),
            ("created_at".into(), self.created_at.to_string()),
            ("retries".into(), self.retries.to_string()),
            ("max_retries".into(), self.max_retries.to_string()),
            ("task_type".into(), self.task_type.clone()),
            ("payload".into(), self.payload.clone()),
            ("channel".into(), self.channel.clone()),
            ("user_id".into(), self.user_id.clone()),
            ("session_id".into(), self.session_id.clone()),
        ];
        if let Some(ref v) = self.started_at {
            fields.push(("started_at".into(), v.to_string()));
        }
        if let Some(ref v) = self.completed_at {
            fields.push(("completed_at".into(), v.to_string()));
        }
        if let Some(ref v) = self.result {
            fields.push(("result".into(), v.clone()));
        }
        if let Some(ref v) = self.error {
            fields.push(("error".into(), v.clone()));
        }
        fields
    }

    /// Parse from Redis hash map.
    fn from_hash(map: &std::collections::HashMap<String, String>) -> Option<Self> {
        let id = map.get("id")?.clone();
        Some(TaskItem {
            id,
            title: map.get("title").cloned().unwrap_or_default(),
            description: map.get("description").cloned().unwrap_or_default(),
            status: map.get("status").cloned().unwrap_or_default(),
            priority: map.get("priority").and_then(|v| v.parse().ok()).unwrap_or(5),
            created_at: map.get("created_at").and_then(|v| v.parse().ok()).unwrap_or(0.0),
            started_at: map.get("started_at").and_then(|v| v.parse().ok()),
            completed_at: map.get("completed_at").and_then(|v| v.parse().ok()),
            result: map.get("result").cloned(),
            error: map.get("error").cloned(),
            channel: map.get("channel").cloned().unwrap_or_default(),
            user_id: map.get("user_id").cloned().unwrap_or_default(),
            session_id: map.get("session_id").cloned().unwrap_or_default(),
            retries: map.get("retries").and_then(|v| v.parse().ok()).unwrap_or(0),
            max_retries: map.get("max_retries").and_then(|v| v.parse().ok()).unwrap_or(3),
            task_type: map.get("task_type").cloned().unwrap_or_default(),
            payload: map.get("payload").cloned().unwrap_or_else(|| "{}".to_string()),
        })
    }
}

const TASK_KEY_PREFIX: &str = "somer:tasks:";
const QUEUE_PENDING: &str = "somer:queue:pending";
const STATUS_SET_PREFIX: &str = "somer:tasks:status:";
const USER_SET_PREFIX: &str = "somer:tasks:user:";
const COMPLETED_TTL: u64 = 86400; // 24 hours

/// Redis-backed task queue.
#[pyclass]
struct TaskQueue {
    conn: Mutex<Connection>,
    #[allow(dead_code)]
    client: Client,
}

#[pymethods]
impl TaskQueue {
    #[new]
    fn new(redis_url: &str) -> PyResult<Self> {
        let client = Client::open(redis_url)
            .map_err(|e| PyRuntimeError::new_err(format!("Redis connect error: {}", e)))?;
        let conn = client
            .get_connection()
            .map_err(|e| PyRuntimeError::new_err(format!("Redis connection error: {}", e)))?;
        Ok(TaskQueue {
            conn: Mutex::new(conn),
            client,
        })
    }

    /// Submit a task to the queue. Returns the task ID.
    fn submit(&self, task: &TaskItem) -> PyResult<String> {
        let mut conn = self.conn.lock()
            .map_err(|e| PyRuntimeError::new_err(format!("Lock error: {}", e)))?;

        let task_key = format!("{}{}", TASK_KEY_PREFIX, task.id);
        let fields = task.to_hash_fields();

        // Store task hash
        let _: () = redis::cmd("HSET")
            .arg(&task_key)
            .arg(&fields)
            .query(&mut *conn)
            .map_err(|e| PyRuntimeError::new_err(format!("Redis HSET error: {}", e)))?;

        // Add to pending sorted set: score = priority * 1_000_000 + timestamp for FIFO
        let score = (task.priority as f64) * 1_000_000.0 + task.created_at;
        let _: () = conn.zadd(QUEUE_PENDING, &task.id, score)
            .map_err(|e| PyRuntimeError::new_err(format!("Redis ZADD error: {}", e)))?;

        // Add to status set
        let status_key = format!("{}{}", STATUS_SET_PREFIX, task.status);
        let _: () = conn.sadd(&status_key, &task.id)
            .map_err(|e| PyRuntimeError::new_err(format!("Redis SADD status error: {}", e)))?;

        // Add to user set
        if !task.user_id.is_empty() {
            let user_key = format!("{}{}", USER_SET_PREFIX, task.user_id);
            let _: () = conn.sadd(&user_key, &task.id)
                .map_err(|e| PyRuntimeError::new_err(format!("Redis SADD user error: {}", e)))?;
        }

        Ok(task.id.clone())
    }

    /// Dequeue the highest-priority task (lowest score). Atomic pop.
    fn dequeue(&self) -> PyResult<Option<TaskItem>> {
        let mut conn = self.conn.lock()
            .map_err(|e| PyRuntimeError::new_err(format!("Lock error: {}", e)))?;

        // ZPOPMIN returns the member with the lowest score
        let result: Vec<(String, f64)> = redis::cmd("ZPOPMIN")
            .arg(QUEUE_PENDING)
            .arg(1i64)
            .query(&mut *conn)
            .map_err(|e| PyRuntimeError::new_err(format!("Redis ZPOPMIN error: {}", e)))?;

        if result.is_empty() {
            return Ok(None);
        }

        let task_id = &result[0].0;
        let task_key = format!("{}{}", TASK_KEY_PREFIX, task_id);

        let map: std::collections::HashMap<String, String> = conn.hgetall(&task_key)
            .map_err(|e| PyRuntimeError::new_err(format!("Redis HGETALL error: {}", e)))?;

        if map.is_empty() {
            return Ok(None);
        }

        // Move from pending status set to running
        let _: () = conn.srem(&format!("{}pending", STATUS_SET_PREFIX), task_id)
            .map_err(|e| PyRuntimeError::new_err(format!("Redis SREM error: {}", e)))?;

        TaskItem::from_hash(&map).ok_or_else(|| {
            PyRuntimeError::new_err("Failed to parse task from Redis hash")
        }).map(Some)
    }

    /// Update task status, optionally setting result or error.
    #[pyo3(signature = (task_id, status, result=None, error=None))]
    fn update_status(
        &self,
        task_id: &str,
        status: &str,
        result: Option<&str>,
        error: Option<&str>,
    ) -> PyResult<bool> {
        let mut conn = self.conn.lock()
            .map_err(|e| PyRuntimeError::new_err(format!("Lock error: {}", e)))?;

        let task_key = format!("{}{}", TASK_KEY_PREFIX, task_id);
        let exists: bool = conn.exists(&task_key)
            .map_err(|e| PyRuntimeError::new_err(format!("Redis EXISTS error: {}", e)))?;
        if !exists {
            return Ok(false);
        }

        // Get old status to remove from old status set
        let old_status: Option<String> = conn.hget(&task_key, "status")
            .map_err(|e| PyRuntimeError::new_err(format!("Redis HGET error: {}", e)))?;
        if let Some(ref old) = old_status {
            let _: () = conn.srem(&format!("{}{}", STATUS_SET_PREFIX, old), task_id)
                .map_err(|e| PyRuntimeError::new_err(format!("Redis SREM error: {}", e)))?;
        }

        // Build update fields
        let mut fields: Vec<(&str, String)> = vec![("status", status.to_string())];
        let now = chrono::Utc::now().timestamp_millis() as f64 / 1000.0;

        if status == "running" {
            fields.push(("started_at", now.to_string()));
        }
        if status == "done" || status == "failed" || status == "cancelled" {
            fields.push(("completed_at", now.to_string()));
        }
        if let Some(r) = result {
            fields.push(("result", r.to_string()));
        }
        if let Some(e) = error {
            fields.push(("error", e.to_string()));
        }

        let _: () = redis::cmd("HSET")
            .arg(&task_key)
            .arg(&fields)
            .query(&mut *conn)
            .map_err(|e| PyRuntimeError::new_err(format!("Redis HSET error: {}", e)))?;

        // Add to new status set
        let _: () = conn.sadd(&format!("{}{}", STATUS_SET_PREFIX, status), task_id)
            .map_err(|e| PyRuntimeError::new_err(format!("Redis SADD error: {}", e)))?;

        // Set TTL on completed tasks
        if status == "done" || status == "failed" || status == "cancelled" {
            let _: () = conn.expire(&task_key, COMPLETED_TTL as i64)
                .map_err(|e| PyRuntimeError::new_err(format!("Redis EXPIRE error: {}", e)))?;
        }

        Ok(true)
    }

    /// Get a task by ID.
    fn get_task(&self, task_id: &str) -> PyResult<Option<TaskItem>> {
        let mut conn = self.conn.lock()
            .map_err(|e| PyRuntimeError::new_err(format!("Lock error: {}", e)))?;

        let task_key = format!("{}{}", TASK_KEY_PREFIX, task_id);
        let map: std::collections::HashMap<String, String> = conn.hgetall(&task_key)
            .map_err(|e| PyRuntimeError::new_err(format!("Redis HGETALL error: {}", e)))?;

        if map.is_empty() {
            return Ok(None);
        }

        Ok(TaskItem::from_hash(&map))
    }

    /// List tasks, optionally filtered by status and/or user_id.
    #[pyo3(signature = (status=None, user_id=None, limit=20))]
    fn list_tasks(
        &self,
        status: Option<&str>,
        user_id: Option<&str>,
        limit: usize,
    ) -> PyResult<Vec<TaskItem>> {
        let mut conn = self.conn.lock()
            .map_err(|e| PyRuntimeError::new_err(format!("Lock error: {}", e)))?;

        let task_ids: Vec<String> = if let Some(s) = status {
            if let Some(u) = user_id {
                // Intersection of status set and user set
                let status_key = format!("{}{}", STATUS_SET_PREFIX, s);
                let user_key = format!("{}{}", USER_SET_PREFIX, u);
                let temp_key = format!("somer:temp:intersect:{}", uuid::Uuid::new_v4());
                let _: () = redis::cmd("SINTERSTORE")
                    .arg(&temp_key)
                    .arg(&status_key)
                    .arg(&user_key)
                    .query(&mut *conn)
                    .map_err(|e| PyRuntimeError::new_err(format!("Redis SINTERSTORE error: {}", e)))?;
                let ids: Vec<String> = conn.smembers(&temp_key)
                    .map_err(|e| PyRuntimeError::new_err(format!("Redis SMEMBERS error: {}", e)))?;
                let _: () = conn.del(&temp_key)
                    .map_err(|e| PyRuntimeError::new_err(format!("Redis DEL error: {}", e)))?;
                ids
            } else {
                let key = format!("{}{}", STATUS_SET_PREFIX, s);
                conn.smembers(&key)
                    .map_err(|e| PyRuntimeError::new_err(format!("Redis SMEMBERS error: {}", e)))?
            }
        } else if let Some(u) = user_id {
            let key = format!("{}{}", USER_SET_PREFIX, u);
            conn.smembers(&key)
                .map_err(|e| PyRuntimeError::new_err(format!("Redis SMEMBERS error: {}", e)))?
        } else {
            // Get all known task IDs from all status sets
            let mut all_ids: Vec<String> = Vec::new();
            for s in &["pending", "running", "done", "failed", "cancelled"] {
                let key = format!("{}{}", STATUS_SET_PREFIX, s);
                let ids: Vec<String> = conn.smembers(&key).unwrap_or_default();
                all_ids.extend(ids);
            }
            all_ids
        };

        let mut tasks = Vec::new();
        for tid in task_ids.iter().take(limit) {
            let task_key = format!("{}{}", TASK_KEY_PREFIX, tid);
            let map: std::collections::HashMap<String, String> = conn.hgetall(&task_key)
                .unwrap_or_default();
            if !map.is_empty() {
                if let Some(task) = TaskItem::from_hash(&map) {
                    tasks.push(task);
                }
            }
        }

        // Sort by created_at descending
        tasks.sort_by(|a, b| b.created_at.partial_cmp(&a.created_at).unwrap_or(std::cmp::Ordering::Equal));

        Ok(tasks)
    }

    /// Cancel a task.
    fn cancel(&self, task_id: &str) -> PyResult<bool> {
        let mut conn = self.conn.lock()
            .map_err(|e| PyRuntimeError::new_err(format!("Lock error: {}", e)))?;

        let task_key = format!("{}{}", TASK_KEY_PREFIX, task_id);
        let exists: bool = conn.exists(&task_key)
            .map_err(|e| PyRuntimeError::new_err(format!("Redis EXISTS error: {}", e)))?;
        if !exists {
            return Ok(false);
        }

        // Remove from pending queue
        let _: () = conn.zrem(QUEUE_PENDING, task_id)
            .map_err(|e| PyRuntimeError::new_err(format!("Redis ZREM error: {}", e)))?;

        // Update status
        drop(conn);
        self.update_status(task_id, "cancelled", None, Some("Cancelled by user"))
    }

    /// Get queue statistics as JSON string.
    fn stats(&self) -> PyResult<String> {
        let mut conn = self.conn.lock()
            .map_err(|e| PyRuntimeError::new_err(format!("Lock error: {}", e)))?;

        let mut counts = serde_json::Map::new();
        for status in &["pending", "running", "done", "failed", "cancelled"] {
            let key = format!("{}{}", STATUS_SET_PREFIX, status);
            let count: u64 = conn.scard(&key).unwrap_or(0);
            counts.insert(status.to_string(), serde_json::Value::Number(count.into()));
        }

        let queue_depth: u64 = conn.zcard(QUEUE_PENDING).unwrap_or(0);
        counts.insert("queue_depth".to_string(), serde_json::Value::Number(queue_depth.into()));

        let result = serde_json::Value::Object(counts);
        Ok(result.to_string())
    }

    /// Cleanup completed tasks older than N seconds. Returns count of removed tasks.
    fn cleanup(&self, older_than_secs: u64) -> PyResult<u64> {
        let mut conn = self.conn.lock()
            .map_err(|e| PyRuntimeError::new_err(format!("Lock error: {}", e)))?;

        let cutoff = chrono::Utc::now().timestamp_millis() as f64 / 1000.0 - older_than_secs as f64;
        let mut removed: u64 = 0;

        for status in &["done", "failed", "cancelled"] {
            let key = format!("{}{}", STATUS_SET_PREFIX, status);
            let ids: Vec<String> = conn.smembers(&key).unwrap_or_default();
            for tid in ids {
                let task_key = format!("{}{}", TASK_KEY_PREFIX, tid);
                let completed_at: Option<f64> = conn.hget(&task_key, "completed_at").ok();
                if let Some(ts) = completed_at {
                    if ts < cutoff {
                        // Get user_id for cleanup
                        let user_id: Option<String> = conn.hget(&task_key, "user_id").ok();

                        let _: () = conn.del(&task_key).unwrap_or(());
                        let _: () = conn.srem(&key, &tid).unwrap_or(());

                        if let Some(uid) = user_id {
                            if !uid.is_empty() {
                                let user_key = format!("{}{}", USER_SET_PREFIX, uid);
                                let _: () = conn.srem(&user_key, &tid).unwrap_or(());
                            }
                        }
                        removed += 1;
                    }
                }
            }
        }

        Ok(removed)
    }
}

/// Python module definition.
#[pymodule]
fn somer_taskqueue(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<TaskItem>()?;
    m.add_class::<TaskQueue>()?;
    Ok(())
}
