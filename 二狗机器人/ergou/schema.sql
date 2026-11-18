PRAGMA user_version = 3;
CREATE TABLE IF NOT EXISTS account (
 id TEXT PRIMARY KEY, mode TEXT NOT NULL CHECK(mode IN ('simulation','adapter')), state TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS membership (
 account TEXT NOT NULL REFERENCES account, grp TEXT NOT NULL, PRIMARY KEY(account,grp)
);
CREATE TABLE IF NOT EXISTS groups (
 id TEXT PRIMARY KEY, account TEXT NOT NULL REFERENCES account, binding INTEGER NOT NULL DEFAULT 1,
 paused INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1, config TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS managers (
 grp TEXT NOT NULL REFERENCES groups, member TEXT NOT NULL, PRIMARY KEY(grp,member)
);
CREATE TABLE IF NOT EXISTS inbox (
 seq INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, source TEXT NOT NULL, account TEXT NOT NULL REFERENCES account,
 grp TEXT NOT NULL REFERENCES groups, member TEXT NOT NULL, kind TEXT NOT NULL, message_type TEXT NOT NULL,
 arrived REAL NOT NULL, binding INTEGER NOT NULL, adapter_version TEXT NOT NULL, trace TEXT NOT NULL,
 payload TEXT, state TEXT NOT NULL, result TEXT, retries INTEGER NOT NULL DEFAULT 0,
 UNIQUE(account,source)
);
CREATE INDEX IF NOT EXISTS inbox_pending ON inbox(state,seq);
CREATE INDEX IF NOT EXISTS inbox_time ON inbox(grp,arrived);
CREATE TABLE IF NOT EXISTS games (
 id INTEGER PRIMARY KEY, grp TEXT NOT NULL REFERENCES groups, code TEXT NOT NULL, game TEXT NOT NULL,
 owner TEXT NOT NULL, state TEXT NOT NULL, rules TEXT NOT NULL, board TEXT NOT NULL, started REAL NOT NULL,
 deadline REAL NOT NULL, ended REAL, reason TEXT, UNIQUE(grp,code)
);
CREATE INDEX IF NOT EXISTS games_group ON games(grp,state);
CREATE TABLE IF NOT EXISTS players (
 game INTEGER NOT NULL REFERENCES games, member TEXT NOT NULL, joined REAL NOT NULL, PRIMARY KEY(game,member)
);
CREATE TABLE IF NOT EXISTS participation (
 game INTEGER NOT NULL REFERENCES games, member TEXT NOT NULL, joined REAL NOT NULL, PRIMARY KEY(game,member)
);
CREATE TRIGGER IF NOT EXISTS record_first_participation AFTER INSERT ON players
 BEGIN INSERT OR IGNORE INTO participation(game,member,joined) VALUES(NEW.game,NEW.member,NEW.joined); END;
CREATE TABLE IF NOT EXISTS ledger (
 id INTEGER PRIMARY KEY, grp TEXT NOT NULL REFERENCES groups, member TEXT NOT NULL, game INTEGER REFERENCES games,
 round INTEGER NOT NULL, kind TEXT NOT NULL, points INTEGER NOT NULL, rule_version TEXT NOT NULL,
 event TEXT NOT NULL, at REAL NOT NULL, reason TEXT NOT NULL, UNIQUE(game,round,member,kind)
);
CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON ledger BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON ledger BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TABLE IF NOT EXISTS outbox (
 id INTEGER PRIMARY KEY, biz TEXT UNIQUE NOT NULL, account TEXT NOT NULL REFERENCES account, grp TEXT NOT NULL REFERENCES groups,
 binding INTEGER NOT NULL, body TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, ready REAL NOT NULL, lease REAL, detail TEXT, ack_at REAL
);
CREATE INDEX IF NOT EXISTS sending_queue ON outbox(state,ready,id);
CREATE TABLE IF NOT EXISTS attempts (
 task INTEGER NOT NULL REFERENCES outbox, n INTEGER NOT NULL, started REAL NOT NULL, ended REAL, result TEXT,
 PRIMARY KEY(task,n)
);
CREATE TABLE IF NOT EXISTS schedules (
 id INTEGER PRIMARY KEY, grp TEXT NOT NULL REFERENCES groups, body TEXT NOT NULL, period TEXT NOT NULL,
 due REAL NOT NULL, catchup INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
 until REAL, version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS runs (
 schedule INTEGER NOT NULL REFERENCES schedules, due REAL NOT NULL, result TEXT NOT NULL, PRIMARY KEY(schedule,due)
);
CREATE TABLE IF NOT EXISTS polls (
 id INTEGER PRIMARY KEY, grp TEXT NOT NULL REFERENCES groups, title TEXT NOT NULL, options TEXT NOT NULL,
 multi INTEGER NOT NULL, owner TEXT NOT NULL, deadline REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ballots (
 poll INTEGER NOT NULL REFERENCES polls, member TEXT NOT NULL, choices TEXT NOT NULL, PRIMARY KEY(poll,member)
);
CREATE TABLE IF NOT EXISTS candidates (
 grp TEXT NOT NULL REFERENCES groups, member TEXT NOT NULL, PRIMARY KEY(grp,member)
);
CREATE TABLE IF NOT EXISTS draws (
 id INTEGER PRIMARY KEY, grp TEXT NOT NULL REFERENCES groups, event TEXT NOT NULL UNIQUE, member TEXT NOT NULL,
 at REAL NOT NULL, pool TEXT NOT NULL, winners TEXT NOT NULL, reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS known_members (
 grp TEXT NOT NULL REFERENCES groups, member TEXT NOT NULL, PRIMARY KEY(grp,member)
);
CREATE TABLE IF NOT EXISTS hits (
 id INTEGER PRIMARY KEY, grp TEXT NOT NULL REFERENCES groups, seq INTEGER NOT NULL REFERENCES inbox,
 version INTEGER NOT NULL, result TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY, at REAL NOT NULL, actor TEXT NOT NULL, grp TEXT, action TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
 name TEXT PRIMARY KEY, password TEXT NOT NULL, role TEXT NOT NULL, scopes TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tokens (
 digest TEXT PRIMARY KEY, name TEXT NOT NULL REFERENCES users, expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS throttles (
 key TEXT PRIMARY KEY, start REAL NOT NULL, used INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS queries (
 id INTEGER PRIMARY KEY REFERENCES inbox, kind TEXT NOT NULL, argument TEXT, state TEXT NOT NULL,
 lease REAL NOT NULL DEFAULT 0, result TEXT
);
CREATE TABLE IF NOT EXISTS weather_cache (
 city TEXT PRIMARY KEY, at REAL NOT NULL, reply TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS breaker (
 kind TEXT PRIMARY KEY, failures INTEGER NOT NULL, reopen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS plugin_registry (
 id TEXT NOT NULL, version TEXT NOT NULL, active INTEGER NOT NULL, manifest TEXT NOT NULL,
 PRIMARY KEY(id,version)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_plugin_version ON plugin_registry(id) WHERE active=1;
CREATE TABLE IF NOT EXISTS retention (
 grp TEXT PRIMARY KEY REFERENCES groups, notice TEXT NOT NULL, since REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS recalls (
 seq INTEGER PRIMARY KEY REFERENCES inbox, grp TEXT NOT NULL REFERENCES groups, source TEXT NOT NULL, at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS operations (
 key TEXT NOT NULL, grp TEXT NOT NULL REFERENCES groups, signature TEXT NOT NULL, result TEXT NOT NULL,
 PRIMARY KEY(grp,key)
);
CREATE TABLE IF NOT EXISTS nodes (
 account TEXT PRIMARY KEY REFERENCES account, secret_hash TEXT NOT NULL UNIQUE,
 last_seen REAL, version TEXT, caps TEXT NOT NULL DEFAULT '{}', issue TEXT
);
CREATE TABLE IF NOT EXISTS node_grants (
 account TEXT NOT NULL REFERENCES nodes(account), grp TEXT NOT NULL REFERENCES groups, PRIMARY KEY(account,grp)
);
CREATE TABLE IF NOT EXISTS listener_nodes (
 account TEXT PRIMARY KEY REFERENCES nodes(account)
);
CREATE TABLE IF NOT EXISTS chat_models (
 grp TEXT PRIMARY KEY REFERENCES groups, version INTEGER NOT NULL, provider TEXT NOT NULL,
 model TEXT NOT NULL, credential BLOB, verified REAL
);
CREATE TABLE IF NOT EXISTS chat_requests (
 seq INTEGER PRIMARY KEY REFERENCES inbox, version INTEGER NOT NULL, prompt TEXT,
 state TEXT NOT NULL DEFAULT 'PENDING', lease REAL
);
CREATE INDEX IF NOT EXISTS chat_request_queue ON chat_requests(state,seq);
CREATE TABLE IF NOT EXISTS chat_voice_context (
 seq INTEGER PRIMARY KEY REFERENCES chat_requests(seq) ON DELETE CASCADE, generation INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS smart_controls (
 grp TEXT PRIMARY KEY REFERENCES groups, version INTEGER NOT NULL DEFAULT 0,
 enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
 generation INTEGER NOT NULL DEFAULT 0, admins TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS local_turns (
 seq INTEGER PRIMARY KEY REFERENCES inbox, grp TEXT NOT NULL, member TEXT NOT NULL,
 binding INTEGER NOT NULL, at REAL NOT NULL, topic TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS local_member_turns ON local_turns(grp,member,binding,seq);
CREATE TABLE IF NOT EXISTS reply_rule_sets (
 grp TEXT PRIMARY KEY REFERENCES groups, version INTEGER NOT NULL, rules TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reply_rule_hits (
 seq INTEGER PRIMARY KEY REFERENCES inbox, keyword TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS simulation_reply_images(
 seq INTEGER PRIMARY KEY REFERENCES inbox, url TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS service_failures (
 id INTEGER PRIMARY KEY, grp TEXT NOT NULL REFERENCES groups, seq INTEGER REFERENCES inbox,
 kind TEXT NOT NULL, reason TEXT NOT NULL, at REAL NOT NULL, UNIQUE(seq,kind)
);
CREATE INDEX IF NOT EXISTS service_failures_by_group ON service_failures(grp,at);
CREATE TABLE IF NOT EXISTS directed_groups (
 grp TEXT PRIMARY KEY REFERENCES groups, account TEXT NOT NULL, binding INTEGER NOT NULL, since REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS directed_events (
 biz TEXT PRIMARY KEY REFERENCES inbox(event_id), source_time REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_wechat_links (
 slot TEXT NOT NULL, account TEXT NOT NULL REFERENCES listener_nodes(account),
 grp TEXT NOT NULL REFERENCES groups(id), server_id TEXT NOT NULL, cursor TEXT NOT NULL,
 PRIMARY KEY(slot,grp), UNIQUE(account)
);
CREATE TABLE IF NOT EXISTS live_notices (
 schedule INTEGER PRIMARY KEY REFERENCES schedules, grp TEXT NOT NULL, account TEXT NOT NULL,
 binding INTEGER NOT NULL, sender_since REAL NOT NULL, server_id TEXT NOT NULL,
 version INTEGER NOT NULL, due REAL NOT NULL, body TEXT NOT NULL,
 biz TEXT NOT NULL UNIQUE, approved REAL NOT NULL
);
CREATE VIEW IF NOT EXISTS valid_live_notices AS
 SELECT n.* FROM live_notices n
 JOIN schedules s ON s.id=n.schedule AND s.grp=n.grp AND s.version=n.version
      AND s.period='一次' AND s.due=n.due AND s.body=n.body
 JOIN groups g ON g.id=n.grp AND g.account=n.account AND g.binding=n.binding AND g.paused=0
 JOIN directed_groups p ON p.grp=n.grp AND p.account=n.account AND p.binding=n.binding AND p.since=n.sender_since
 JOIN agent_wechat_links l ON l.grp=n.grp AND l.account=n.account AND l.server_id=n.server_id
 WHERE NOT EXISTS(SELECT 1 FROM bulletin_types t WHERE t.schedule=s.id);
CREATE TABLE IF NOT EXISTS weekly (
 grp TEXT NOT NULL REFERENCES groups, start REAL NOT NULL, report TEXT NOT NULL, PRIMARY KEY(grp,start)
);
CREATE TABLE IF NOT EXISTS group_alert (
 id INTEGER PRIMARY KEY, grp TEXT NOT NULL REFERENCES groups, kind TEXT NOT NULL,
 opened REAL NOT NULL, recovered REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_alert ON group_alert(grp,kind) WHERE recovered IS NULL;
CREATE TABLE IF NOT EXISTS config_history (
 grp TEXT NOT NULL, version INTEGER NOT NULL, at REAL NOT NULL, snapshot TEXT NOT NULL,
 PRIMARY KEY(grp,version)
);
CREATE TABLE IF NOT EXISTS account_policy (
 account TEXT PRIMARY KEY REFERENCES account, per_second INTEGER NOT NULL CHECK(per_second BETWEEN 1 AND 100)
);
CREATE TABLE IF NOT EXISTS observation (
 grp TEXT NOT NULL REFERENCES groups, minute INTEGER NOT NULL, PRIMARY KEY(grp,minute)
);
CREATE TABLE IF NOT EXISTS welcomes (
 grp TEXT NOT NULL REFERENCES groups, account TEXT NOT NULL, binding INTEGER NOT NULL,
 member TEXT NOT NULL, name TEXT NOT NULL, due REAL NOT NULL, PRIMARY KEY(grp,member)
);
CREATE TABLE IF NOT EXISTS inbox_capacity (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), count INTEGER NOT NULL, bytes INTEGER NOT NULL
);
INSERT OR IGNORE INTO inbox_capacity SELECT 1,COUNT(*),COALESCE(SUM(LENGTH(CAST(payload AS BLOB))),0) FROM inbox WHERE state='PENDING';
CREATE TRIGGER IF NOT EXISTS capacity_insert AFTER INSERT ON inbox WHEN NEW.state='PENDING'
 BEGIN UPDATE inbox_capacity SET count=count+1,bytes=bytes+COALESCE(LENGTH(CAST(NEW.payload AS BLOB)),0); END;
CREATE TRIGGER IF NOT EXISTS capacity_change AFTER UPDATE OF state,payload ON inbox
 BEGIN UPDATE inbox_capacity SET count=count+(NEW.state='PENDING')-(OLD.state='PENDING'),
 bytes=bytes+CASE WHEN NEW.state='PENDING' THEN COALESCE(LENGTH(CAST(NEW.payload AS BLOB)),0) ELSE 0 END
 -CASE WHEN OLD.state='PENDING' THEN COALESCE(LENGTH(CAST(OLD.payload AS BLOB)),0) ELSE 0 END; END;

