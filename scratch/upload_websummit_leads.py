#!/usr/bin/env python3
"""
Web Summit Vancouver 2026 -> Attio batch upload via Inform Gateway.

Resumable, idempotent, concurrent. Three stages:
  1. Upsert companies by domain   (~434 calls)
  2. Upsert people by email       (~640 calls)
  3. Add people to Web Summit list (~640 calls)

Total: ~1,714 calls. Expect 10-25 minutes with concurrency=5.

USAGE:
  export GATEWAY_URL="https://inform-gateway-production.up.railway.app/mcp"
  export GATEWAY_API_KEY="<your-key>"
  python upload_websummit_leads.py --payloads attio_payloads_v3.jsonl \\
                                   --companies company_upsert_plan.jsonl \\
                                   --list-id 3cd77fa7-98da-4679-a277-5577a07b9419

State files (written to --state-dir, default ./state):
  domain_to_company_id.json   - domain -> company record_id
  people_results.jsonl        - one row per person upsert
  list_results.jsonl          - one row per list-entry add
  failures.jsonl              - all failures with full context

Re-running picks up where it left off. Safe to interrupt.
"""

import argparse
import json
import os
import re
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import requests


# ----- MCP client (JSON-RPC over Streamable HTTP) ----- #

class GatewayClient:
    """Minimal MCP client for the Inform Gateway. Calls tools via JSON-RPC."""

    def __init__(self, url: str, api_key: str, task_id: str):
        self.url = url
        self.api_key = api_key
        self.task_id = task_id
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        })
        self._id_lock = Lock()
        self._next_id = 0
        self._session_id = None

    def _new_id(self) -> int:
        with self._id_lock:
            self._next_id += 1
            return self._next_id

    def _initialize(self):
        """MCP handshake. Captures the session id for subsequent calls."""
        payload = {
            "jsonrpc": "2.0",
            "id": self._new_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "websummit-uploader", "version": "1.0"},
            },
        }
        r = self.session.post(self.url, json=payload, timeout=60)
        r.raise_for_status()
        self._session_id = r.headers.get("mcp-session-id")
        if self._session_id:
            self.session.headers["mcp-session-id"] = self._session_id

        # Required notification per MCP spec
        notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        self.session.post(self.url, json=notif, timeout=30)

    def call_tool(self, name: str, arguments: dict, *, retries: int = 3, backoff: float = 2.0):
        """Call an MCP tool. Auto-injects task_id. Retries on transient errors."""
        if "task_id" not in arguments and name not in ("declare_intent", "get_tasks"):
            arguments["task_id"] = self.task_id

        payload = {
            "jsonrpc": "2.0",
            "id": self._new_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }

        last_err = None
        for attempt in range(retries):
            try:
                r = self.session.post(self.url, json=payload, timeout=120)
                if r.status_code == 429:
                    wait = backoff ** (attempt + 1)
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                # Streamable HTTP may return SSE-framed text/event-stream
                ct = r.headers.get("content-type", "")
                if "text/event-stream" in ct:
                    data = _parse_sse(r.text)
                else:
                    data = r.json()
                if "error" in data:
                    raise RuntimeError(f"JSON-RPC error: {data['error']}")
                # Tool results live in result.content[0].text typically, but the Gateway
                # returns structured content. Pass back the full result for the caller.
                return data.get("result", {})
            except (requests.RequestException, RuntimeError) as e:
                last_err = e
                time.sleep(backoff * (attempt + 1))
        raise RuntimeError(f"Tool {name} failed after {retries} retries: {last_err}")


def _parse_sse(text: str) -> dict:
    """Pull the final JSON-RPC message out of an SSE stream."""
    last_data = None
    for line in text.splitlines():
        if line.startswith("data: "):
            last_data = line[6:]
    if not last_data:
        raise RuntimeError(f"No data lines in SSE response: {text[:200]}")
    return json.loads(last_data)


def extract_tool_payload(result: dict) -> dict:
    """Tool results come back inside result.content. Pull the structured payload."""
    content = result.get("content", [])
    if not content:
        return result
    first = content[0]
    if first.get("type") == "text":
        try:
            return json.loads(first["text"])
        except (json.JSONDecodeError, KeyError):
            return {"_raw_text": first.get("text", "")}
    return first


# ----- State management ----- #

class State:
    """File-backed state for resumability. Each stage writes one JSONL row per item."""

    def __init__(self, state_dir: Path):
        self.dir = state_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.domain_map_path = self.dir / "domain_to_company_id.json"
        self.people_path = self.dir / "people_results.jsonl"
        self.list_path = self.dir / "list_results.jsonl"
        self.failures_path = self.dir / "failures.jsonl"
        self._lock = Lock()

    def load_domain_map(self) -> dict:
        if self.domain_map_path.exists():
            return json.loads(self.domain_map_path.read_text())
        return {}

    def save_domain_map(self, mapping: dict):
        with self._lock:
            self.domain_map_path.write_text(json.dumps(mapping, indent=2))

    def load_done_ids(self, path: Path, key: str) -> set:
        if not path.exists():
            return set()
        done = set()
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                if rec.get("status") == "ok" and key in rec:
                    done.add(rec[key])
            except json.JSONDecodeError:
                continue
        return done

    def append(self, path: Path, record: dict):
        with self._lock:
            with open(path, "a") as f:
                f.write(json.dumps(record) + "\n")

    def log_failure(self, stage: str, item: dict, error: str):
        self.append(self.failures_path, {
            "stage": stage,
            "item": item,
            "error": error,
            "ts": time.time(),
        })


# ----- Stage 1: companies ----- #

def upsert_companies(client: GatewayClient, plan: list, state: State, workers: int):
    """Upsert each unique-domain company. Build domain -> record_id map."""
    domain_map = state.load_domain_map()
    todo = [c for c in plan if c["domain"] not in domain_map]
    print(f"[companies] {len(todo)} to upsert, {len(domain_map)} already done")
    if not todo:
        return domain_map

    def _one(item):
        try:
            result = client.call_tool("attio__upsert_record", {
                "object_type": "companies",
                "matching_attribute": "domains",
                "values": {
                    "domains": [{"domain": item["domain"]}],
                    "name": [{"value": item["name"]}],
                },
            })
            payload = extract_tool_payload(result)
            rid = payload.get("record_id") or payload.get("data", {}).get("id", {}).get("record_id")
            if not rid:
                raise RuntimeError(f"No record_id in response: {payload}")
            return item, rid, None
        except Exception as e:
            # Attio raises uniqueness_conflict when another record already owns the domain.
            # The error message contains the conflicting record IDs — extract and reuse them.
            match = re.search(r"Conflicting record IDs: ([0-9a-f-]{36})", str(e))
            if match:
                return item, match.group(1), None
            return item, None, str(e)

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, c) for c in todo]
        for fut in as_completed(futures):
            item, rid, err = fut.result()
            done += 1
            if rid:
                domain_map[item["domain"]] = rid
                if done % 25 == 0:
                    state.save_domain_map(domain_map)
                    print(f"[companies] {done}/{len(todo)}")
            else:
                state.log_failure("companies", item, err)
                print(f"[companies] FAIL {item['domain']}: {err}", file=sys.stderr)
    state.save_domain_map(domain_map)
    print(f"[companies] complete: {len(domain_map)} mapped")
    return domain_map


# ----- Stage 2: people ----- #

def upsert_people(client: GatewayClient, payloads: list, domain_map: dict,
                  state: State, workers: int) -> dict:
    """Upsert people, attaching company UUID when domain is in the map. Return id -> record_id."""
    done_ids = state.load_done_ids(state.people_path, "websummit_id")
    todo = [p for p in payloads if p["_meta"]["websummit_id"] not in done_ids]
    print(f"[people] {len(todo)} to upsert, {len(done_ids)} already done")

    person_id_map = {}
    # Pre-populate from prior runs
    if state.people_path.exists():
        for line in state.people_path.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("status") == "ok":
                    person_id_map[rec["websummit_id"]] = rec["record_id"]

    if not todo:
        return person_id_map

    def _one(p):
        meta = p["_meta"]
        values = dict(p["values"])
        # Drop linkedin if it's not a real URL (some records have rationale text there)
        if "linkedin" in values and not str(values["linkedin"]).startswith("http"):
            del values["linkedin"]
        # Attach company reference if we have a UUID for this domain
        domain = meta.get("derived_domain")
        if domain and domain in domain_map:
            values["company"] = [{
                "target_object": "companies",
                "target_record_id": domain_map[domain],
            }]
        try:
            result = client.call_tool("attio__upsert_record", {
                "object_type": "people",
                "matching_attribute": "email_addresses",
                "values": values,
            })
            payload = extract_tool_payload(result)
            rid = payload.get("record_id") or payload.get("data", {}).get("id", {}).get("record_id")
            if not rid:
                raise RuntimeError(f"No record_id in response: {payload}")
            return meta, rid, None
        except Exception as e:
            # Person already exists — extract their record ID from the conflict error.
            match = re.search(r"Conflicting record IDs: ([0-9a-f-]{36})", str(e))
            if match:
                return meta, match.group(1), None
            return meta, None, str(e)

    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, p) for p in todo]
        for fut in as_completed(futures):
            meta, rid, err = fut.result()
            completed += 1
            if rid:
                person_id_map[meta["websummit_id"]] = rid
                state.append(state.people_path, {
                    "status": "ok",
                    "websummit_id": meta["websummit_id"],
                    "name": meta["name"],
                    "record_id": rid,
                    "ts": time.time(),
                })
                if completed % 25 == 0:
                    print(f"[people] {completed}/{len(todo)}")
            else:
                state.append(state.people_path, {
                    "status": "error",
                    "websummit_id": meta["websummit_id"],
                    "name": meta["name"],
                    "error": err,
                    "ts": time.time(),
                })
                state.log_failure("people", meta, err)
                print(f"[people] FAIL {meta['name']}: {err}", file=sys.stderr)
    print(f"[people] complete: {len(person_id_map)} mapped")
    return person_id_map


# ----- Stage 3: list entries ----- #

def add_to_list(client: GatewayClient, person_id_map: dict, list_id: str,
                state: State, workers: int):
    """Add every person to the Web Summit list."""
    done_ids = state.load_done_ids(state.list_path, "record_id")
    todo = [rid for rid in person_id_map.values() if rid not in done_ids]
    print(f"[list] {len(todo)} to add, {len(done_ids)} already done")
    if not todo:
        return

    def _one(rid):
        try:
            result = client.call_tool("attio__manage-list-entry", {
                "kwargs": {
                    "listId": list_id,
                    "recordId": rid,
                    "objectType": "people",
                }
            })
            payload = extract_tool_payload(result)
            entry_id = payload.get("id", {}).get("entry_id") if isinstance(payload, dict) else None
            return rid, entry_id, None
        except Exception as e:
            return rid, None, str(e)

    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, rid) for rid in todo]
        for fut in as_completed(futures):
            rid, entry_id, err = fut.result()
            completed += 1
            if err:
                state.append(state.list_path, {
                    "status": "error",
                    "record_id": rid,
                    "error": err,
                    "ts": time.time(),
                })
                state.log_failure("list", {"record_id": rid}, err)
                print(f"[list] FAIL {rid}: {err}", file=sys.stderr)
            else:
                state.append(state.list_path, {
                    "status": "ok",
                    "record_id": rid,
                    "entry_id": entry_id,
                    "ts": time.time(),
                })
                if completed % 25 == 0:
                    print(f"[list] {completed}/{len(todo)}")
    print(f"[list] complete")


# ----- Main ----- #

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--payloads", required=True, help="Path to attio_payloads_v3.jsonl")
    ap.add_argument("--companies", required=True, help="Path to company_upsert_plan.jsonl")
    ap.add_argument("--list-id", required=True, help="Attio list UUID (Web Summit Vancouver 2026)")
    ap.add_argument("--state-dir", default="./state", help="Where to store progress files")
    ap.add_argument("--workers", type=int, default=5, help="Concurrent requests (default 5)")
    ap.add_argument("--stages", default="1,2,3", help="Stages to run: 1,2,3 (default all)")
    ap.add_argument("--task-id", help="Reuse an existing Gateway task_id (else creates one)")
    args = ap.parse_args()

    gateway_url = os.environ.get("GATEWAY_URL")
    api_key = os.environ.get("GATEWAY_API_KEY")
    if not gateway_url or not api_key:
        print("Set GATEWAY_URL and GATEWAY_API_KEY env vars", file=sys.stderr)
        sys.exit(1)

    state = State(Path(args.state_dir))
    stages = set(args.stages.split(","))

    # Bootstrap a client just to declare intent (or reuse task_id)
    task_id = args.task_id
    if not task_id:
        bootstrap = GatewayClient(gateway_url, api_key, task_id="bootstrap")
        bootstrap._initialize()
        result = bootstrap.call_tool("declare_intent", {
            "goal": "Batch upload Web Summit Vancouver 2026 attendees to Attio",
            "steps": ["upsert companies by domain", "upsert people by email",
                      "add people to Web Summit list"],
        })
        payload = extract_tool_payload(result)
        task_id = payload.get("task_id")
        if not task_id:
            print(f"Failed to declare intent: {payload}", file=sys.stderr)
            sys.exit(1)
        print(f"Task: {task_id}")

    client = GatewayClient(gateway_url, api_key, task_id=task_id)
    client._initialize()

    # Load inputs
    payloads = [json.loads(l) for l in open(args.payloads) if l.strip()]
    company_plan = [json.loads(l) for l in open(args.companies) if l.strip()]
    print(f"Loaded {len(payloads)} people, {len(company_plan)} companies")

    # Stage 1
    if "1" in stages:
        domain_map = upsert_companies(client, company_plan, state, args.workers)
    else:
        domain_map = state.load_domain_map()
        print(f"[companies] skipped, loaded {len(domain_map)} from state")

    # Stage 2
    if "2" in stages:
        person_id_map = upsert_people(client, payloads, domain_map, state, args.workers)
    else:
        person_id_map = {}
        if state.people_path.exists():
            for line in state.people_path.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    if rec.get("status") == "ok":
                        person_id_map[rec["websummit_id"]] = rec["record_id"]
        print(f"[people] skipped, loaded {len(person_id_map)} from state")

    # Stage 3
    if "3" in stages:
        add_to_list(client, person_id_map, args.list_id, state, args.workers)

    # Mark task complete
    try:
        client.call_tool("complete_task", {
            "task_id": task_id,
            "outcome": f"Uploaded {len(person_id_map)} people to Web Summit list",
        })
    except Exception as e:
        print(f"Warning: complete_task failed: {e}", file=sys.stderr)

    # Final summary
    print("\n=== SUMMARY ===")
    print(f"Companies mapped:  {len(state.load_domain_map())}")
    print(f"People upserted:   {len(person_id_map)}")
    if state.failures_path.exists():
        fails = sum(1 for _ in open(state.failures_path))
        print(f"Failures logged:   {fails} (see {state.failures_path})")


if __name__ == "__main__":
    main()
