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
CREATE TABLE IF NOT EXISTS asset_action_holds (
 grp TEXT NOT NULL, member TEXT NOT NULL, seq INTEGER NOT NULL REFERENCES inbox(seq) ON DELETE CASCADE,
 PRIMARY KEY(grp,member)
);
CREATE INDEX IF NOT EXISTS asset_action_event ON asset_action_holds(seq);
CREATE TRIGGER IF NOT EXISTS asset_action_finished AFTER UPDATE OF state ON inbox
 WHEN OLD.state='PENDING' AND NEW.state!='PENDING'
 BEGIN DELETE FROM asset_action_holds WHERE seq=NEW.seq; END;
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
CREATE INDEX IF NOT EXISTS ledger_member_balance ON ledger(grp,member,points);
CREATE UNIQUE INDEX IF NOT EXISTS ledger_exhibit_prize ON ledger(grp,member,kind,event)
 WHERE kind IN ('图鉴日榜','区域图鉴');
CREATE TABLE IF NOT EXISTS exhibit_reward_clock (
 grp TEXT PRIMARY KEY REFERENCES groups, day TEXT NOT NULL, checked INTEGER NOT NULL DEFAULT 0
);
-- 只索引签到流水；先取整秒，避免午夜前的小数秒被日期函数进位。
CREATE UNIQUE INDEX IF NOT EXISTS ledger_checkin_day
 ON ledger(grp,member,date(CAST(at AS INTEGER),'unixepoch','+8 hours')) WHERE kind='签到';
CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON ledger BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON ledger BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TABLE IF NOT EXISTS outbox (
 id INTEGER PRIMARY KEY, biz TEXT UNIQUE NOT NULL, account TEXT NOT NULL REFERENCES account, grp TEXT NOT NULL REFERENCES groups,
 binding INTEGER NOT NULL, body TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, ready REAL NOT NULL, lease REAL, detail TEXT, ack_at REAL
);
CREATE TABLE IF NOT EXISTS music_search_cards (
 task INTEGER PRIMARY KEY REFERENCES outbox(id) ON DELETE CASCADE,
 title TEXT NOT NULL, url TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sending_queue ON outbox(state,ready,id);
CREATE TABLE IF NOT EXISTS exhibit_board_notices(
 task INTEGER PRIMARY KEY REFERENCES outbox(id) ON DELETE CASCADE,
 digest TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
);
CREATE VIEW IF NOT EXISTS valid_exhibit_board_notices AS
 SELECT o.id,o.biz,o.grp,o.account,o.binding,n.digest FROM exhibit_board_notices n
 JOIN outbox o ON o.id=n.task JOIN groups g ON g.id=o.grp AND g.account=o.account AND g.binding=o.binding
 LEFT JOIN group_profile p ON p.grp=g.id
 WHERE n.revoked=0 AND NOT g.paused AND NOT coalesce(p.detached,0)
 AND json_extract(g.config,'$.enabled') AND json_extract(g.config,'$.games')
 AND json_extract(g.config,'$.exhibit_board_push')
 AND NOT EXISTS(SELECT 1 FROM json_each(g.config,'$.disabled_games') WHERE value='钓鱼');
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
CREATE TABLE IF NOT EXISTS fishing_reply_mentions (
 biz TEXT PRIMARY KEY REFERENCES directed_events(biz) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS agent_wechat_links (
 slot TEXT NOT NULL, account TEXT NOT NULL REFERENCES listener_nodes(account),
 grp TEXT NOT NULL REFERENCES groups(id), server_id TEXT NOT NULL, cursor TEXT NOT NULL,
 PRIMARY KEY(slot,grp), UNIQUE(account,grp)
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


CREATE TABLE IF NOT EXISTS fishing_records (
 grp TEXT NOT NULL REFERENCES groups(id), member TEXT NOT NULL,
 count INTEGER NOT NULL, grams INTEGER NOT NULL, best_name TEXT NOT NULL,
 best_grams INTEGER NOT NULL, last_cast REAL NOT NULL, PRIMARY KEY(grp,member)
);
CREATE TABLE IF NOT EXISTS fishing_first_epic (
 grp TEXT NOT NULL REFERENCES groups, member TEXT NOT NULL, casts INTEGER NOT NULL CHECK(casts BETWEEN 0 AND 50),
 landed TEXT, PRIMARY KEY(grp,member)
);
CREATE TABLE IF NOT EXISTS fishing_hotspot_catch (
 grp TEXT NOT NULL REFERENCES groups, member TEXT NOT NULL, hour INTEGER NOT NULL,
 PRIMARY KEY(grp,member)
);
CREATE TABLE IF NOT EXISTS fishing_area_attempts (
 grp TEXT NOT NULL REFERENCES groups, day TEXT NOT NULL, area TEXT NOT NULL,
 casts INTEGER NOT NULL DEFAULT 0, epic_bites INTEGER NOT NULL DEFAULT 0, epic_landed INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(grp,day,area)
);

CREATE TABLE IF NOT EXISTS fishing_wallets (
 grp TEXT NOT NULL REFERENCES groups(id), member TEXT NOT NULL,
 coins INTEGER NOT NULL DEFAULT 30 CHECK(coins>=0),
 rod INTEGER NOT NULL DEFAULT 1 CHECK(rod BETWEEN 1 AND 5),
 PRIMARY KEY(grp,member)
);
CREATE TABLE IF NOT EXISTS fishing_pond (
 id INTEGER PRIMARY KEY AUTOINCREMENT, grp TEXT NOT NULL, member TEXT NOT NULL,
 fish TEXT NOT NULL, grams INTEGER NOT NULL CHECK(grams>0), price INTEGER NOT NULL CHECK(price>0),
 grade INTEGER CHECK(grade BETWEEN 0 AND 5), grade_upgraded INTEGER NOT NULL DEFAULT 0,
 storage TEXT NOT NULL DEFAULT 'pond' CHECK(storage IN ('pond','bag')),
 FOREIGN KEY(grp,member) REFERENCES fishing_wallets(grp,member)
);
CREATE TABLE IF NOT EXISTS fishing_storage_levels (
 grp TEXT NOT NULL, member TEXT NOT NULL, storage TEXT NOT NULL CHECK(storage IN ('pond','bag')),
 level INTEGER NOT NULL CHECK(level BETWEEN 1 AND 5), PRIMARY KEY(grp,member,storage),
 FOREIGN KEY(grp,member) REFERENCES fishing_wallets(grp,member)
);
CREATE INDEX IF NOT EXISTS fishing_inventory_owner ON fishing_pond(grp,member,storage,id);
CREATE INDEX IF NOT EXISTS fishing_pond_owner ON fishing_pond(grp,member,id);

CREATE TABLE IF NOT EXISTS fishing_exhibits (
 grp TEXT NOT NULL, member TEXT NOT NULL, fish TEXT NOT NULL,
 grade INTEGER CHECK(grade BETWEEN 0 AND 5), grade_upgraded INTEGER NOT NULL DEFAULT 0,
 item_id INTEGER NOT NULL UNIQUE, grams INTEGER NOT NULL CHECK(grams>0),
 price INTEGER NOT NULL CHECK(price>0), PRIMARY KEY(grp,member,fish),
 FOREIGN KEY(grp,member) REFERENCES fishing_wallets(grp,member)
);

CREATE TABLE IF NOT EXISTS asset_display_names(
 grp TEXT NOT NULL REFERENCES groups, binding INTEGER NOT NULL, member TEXT NOT NULL,
 name TEXT NOT NULL, checked REAL NOT NULL, PRIMARY KEY(grp,binding,member)
);

CREATE TABLE IF NOT EXISTS fishing_species (
 grp TEXT NOT NULL, member TEXT NOT NULL, fish TEXT NOT NULL, best_grams INTEGER NOT NULL,
 best_grade INTEGER CHECK(best_grade BETWEEN 0 AND 5), best_grade_upgraded INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(grp,member,fish)
);
CREATE TABLE IF NOT EXISTS fishing_tackle (
 grp TEXT NOT NULL, member TEXT NOT NULL, broken INTEGER NOT NULL DEFAULT 0 CHECK(broken IN (0,1)),
 last_attempt REAL NOT NULL, PRIMARY KEY(grp,member)
);
CREATE INDEX IF NOT EXISTS fishing_heaviest ON fishing_records(grp,best_grams DESC,member);

CREATE TABLE IF NOT EXISTS fishing_wear (
 grp TEXT NOT NULL, member TEXT NOT NULL,
 line_wear INTEGER NOT NULL CHECK(line_wear>=0), rod_wear INTEGER NOT NULL CHECK(rod_wear>=0),
 PRIMARY KEY(grp,member), FOREIGN KEY(grp,member) REFERENCES fishing_wallets(grp,member)
);

CREATE TABLE IF NOT EXISTS fishing_line_levels (
 grp TEXT NOT NULL, member TEXT NOT NULL, level INTEGER NOT NULL CHECK(level BETWEEN 1 AND 5),
 PRIMARY KEY(grp,member), FOREIGN KEY(grp,member) REFERENCES fishing_wallets(grp,member)
);

CREATE TABLE IF NOT EXISTS fishing_experience (
 grp TEXT NOT NULL, member TEXT NOT NULL, casts INTEGER NOT NULL CHECK(casts>=1),
 PRIMARY KEY(grp,member), FOREIGN KEY(grp,member) REFERENCES fishing_wallets(grp,member)
);

CREATE TABLE IF NOT EXISTS fishing_waters (
 grp TEXT NOT NULL, member TEXT NOT NULL, area TEXT NOT NULL DEFAULT '外海', PRIMARY KEY(grp,member),
 FOREIGN KEY(grp,member) REFERENCES fishing_wallets(grp,member)
);

CREATE TABLE IF NOT EXISTS fishing_raids (
 grp TEXT NOT NULL REFERENCES groups(id), member TEXT NOT NULL,
 protected_until REAL NOT NULL DEFAULT 0, last_attempt REAL,
 PRIMARY KEY(grp,member)
);

CREATE TABLE IF NOT EXISTS fishing_giant_claims (
 grp TEXT NOT NULL REFERENCES groups(id), area TEXT NOT NULL, start INTEGER NOT NULL,
 PRIMARY KEY(grp,area)
);

CREATE TABLE IF NOT EXISTS fishing_grade_news (
 grp TEXT PRIMARY KEY REFERENCES groups(id), member TEXT NOT NULL, fish TEXT NOT NULL,
 grams INTEGER NOT NULL, grade INTEGER NOT NULL CHECK(grade IN (4,5)),
 upgraded INTEGER NOT NULL, legends INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS binding_streams (
 slot TEXT PRIMARY KEY, account TEXT UNIQUE NOT NULL REFERENCES listener_nodes, server_id TEXT NOT NULL, cursor TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS binding_admins (
 account TEXT NOT NULL REFERENCES listener_nodes, member TEXT NOT NULL, PRIMARY KEY(account,member)
);
CREATE TABLE IF NOT EXISTS binding_pauses (
 grp TEXT PRIMARY KEY REFERENCES groups, binding INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS binding_receipts (
 account TEXT NOT NULL, source TEXT NOT NULL, grp TEXT NOT NULL, member TEXT NOT NULL, body TEXT NOT NULL,
 expires REAL NOT NULL, state TEXT NOT NULL DEFAULT 'PENDING', PRIMARY KEY(account,source)
);
CREATE INDEX IF NOT EXISTS binding_receipt_pending ON binding_receipts(account,state,expires);

-- 鱼获编号在库存与展柜间迁移，养成档案独立于这两张表。
CREATE TABLE IF NOT EXISTS pond_growth (
 item INTEGER PRIMARY KEY, original_grams INTEGER NOT NULL, original_price INTEGER NOT NULL,
 original_grade INTEGER, catcher TEXT, rounds INTEGER NOT NULL DEFAULT 0 CHECK(rounds BETWEEN 0 AND 10),
 appearance INTEGER NOT NULL DEFAULT 0, promoted INTEGER NOT NULL DEFAULT 0,
 food INTEGER NOT NULL DEFAULT 0, first_fed INTEGER NOT NULL DEFAULT 0,
 fed_segment INTEGER NOT NULL DEFAULT 0, next_at REAL, remaining_seconds REAL,
 flagship INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS pond_due ON pond_growth(next_at) WHERE next_at IS NOT NULL;
CREATE TABLE IF NOT EXISTS pond_migrations (version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS pond_activity (
 day TEXT NOT NULL, grp TEXT NOT NULL, member TEXT NOT NULL, action TEXT NOT NULL,
 PRIMARY KEY(day,grp,member,action)
);
CREATE TABLE IF NOT EXISTS pond_coin_flow (
 day TEXT NOT NULL, grp TEXT NOT NULL, net INTEGER NOT NULL, PRIMARY KEY(day,grp)
);
CREATE TRIGGER IF NOT EXISTS pond_wallet_open AFTER INSERT ON fishing_wallets BEGIN
 INSERT INTO pond_coin_flow VALUES(date('now','+8 hours'),new.grp,new.coins)
 ON CONFLICT(day,grp) DO UPDATE SET net=net+excluded.net;
END;
CREATE TRIGGER IF NOT EXISTS pond_wallet_change AFTER UPDATE OF coins ON fishing_wallets
WHEN new.coins!=old.coins BEGIN
 INSERT INTO pond_coin_flow VALUES(date('now','+8 hours'),new.grp,new.coins-old.coins)
 ON CONFLICT(day,grp) DO UPDATE SET net=net+excluded.net;
END;
CREATE TABLE IF NOT EXISTS breed_pairs (
 id INTEGER PRIMARY KEY,grp TEXT NOT NULL,member TEXT NOT NULL,p1 INTEGER NOT NULL,p2 INTEGER NOT NULL,
 fish TEXT NOT NULL,started REAL NOT NULL,due REAL NOT NULL,wins INTEGER NOT NULL,birth INTEGER NOT NULL,
 fee INTEGER NOT NULL, claimed_at REAL, offspring INTEGER UNIQUE,state TEXT NOT NULL CHECK(state IN ('active','pending','failed','cancelled','claimed')),
 CHECK(p1<p2),FOREIGN KEY(grp,member) REFERENCES fishing_wallets(grp,member)
);
CREATE UNIQUE INDEX IF NOT EXISTS breed_one ON breed_pairs(grp,member) WHERE state IN ('active','pending');
CREATE INDEX IF NOT EXISTS breed_history ON breed_pairs(grp,member,id);
CREATE TABLE IF NOT EXISTS breed_fry (
 item INTEGER PRIMARY KEY REFERENCES pond_growth(item) ON DELETE CASCADE,birth INTEGER NOT NULL,adult INTEGER NOT NULL,
 breeder TEXT NOT NULL, firstborn INTEGER NOT NULL CHECK(firstborn IN (0,1))
);
CREATE TRIGGER IF NOT EXISTS breed_leave AFTER DELETE ON fishing_pond WHEN old.storage='pond' BEGIN
 UPDATE breed_pairs SET state='cancelled' WHERE grp=old.grp AND member=old.member AND state='active'
 AND (p1=old.id OR p2=old.id);
END;
CREATE TRIGGER IF NOT EXISTS breed_transfer AFTER UPDATE OF storage,member,grp ON fishing_pond
WHEN old.storage='pond' AND (old.member!=new.member OR old.grp!=new.grp OR new.storage!='pond') BEGIN
 UPDATE breed_pairs SET state='cancelled' WHERE grp=old.grp AND member=old.member AND state='active'
 AND (p1=old.id OR p2=old.id);
END;

CREATE TABLE IF NOT EXISTS breed_pilots (
 grp TEXT PRIMARY KEY REFERENCES groups(id),started REAL NOT NULL,enabled INTEGER NOT NULL CHECK(enabled IN (0,1))
);
CREATE TABLE IF NOT EXISTS breed_previews (
 grp TEXT NOT NULL,member TEXT NOT NULL,p1 INTEGER NOT NULL,p2 INTEGER NOT NULL,expires REAL NOT NULL,
 PRIMARY KEY(grp,member)
);
CREATE TABLE IF NOT EXISTS breed_queries (
 grp TEXT NOT NULL REFERENCES breed_pilots(grp), member TEXT NOT NULL, first_at REAL NOT NULL,
 PRIMARY KEY(grp,member)
);
CREATE TABLE IF NOT EXISTS breed_eligible (
 grp TEXT NOT NULL, member TEXT NOT NULL, ready REAL NOT NULL, PRIMARY KEY(grp,member)
);
CREATE TABLE IF NOT EXISTS breed_sales (
 item INTEGER PRIMARY KEY,grp TEXT NOT NULL,member TEXT NOT NULL,at REAL NOT NULL,price INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS breed_sales_week ON breed_sales(grp,at);
CREATE TABLE IF NOT EXISTS breed_transfers (
 id INTEGER PRIMARY KEY,item INTEGER NOT NULL,member TEXT NOT NULL,at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS breed_transfers_item ON breed_transfers(item,at,id);

-- 江湖角色、货币、章节及群开关与既有玩法隔离。
CREATE TABLE IF NOT EXISTS jh_group_config (
 grp TEXT PRIMARY KEY REFERENCES groups, enabled INTEGER NOT NULL, version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS jh_drafts (
 grp TEXT NOT NULL REFERENCES groups, member TEXT NOT NULL, identity TEXT, stats TEXT,
 PRIMARY KEY(grp,member)
);
CREATE TABLE IF NOT EXISTS jh_players (
 grp TEXT NOT NULL REFERENCES groups, member TEXT NOT NULL, identity TEXT NOT NULL,
 strength INTEGER NOT NULL, agility INTEGER NOT NULL, constitution INTEGER NOT NULL,
 insight INTEGER NOT NULL, luck INTEGER NOT NULL, title TEXT NOT NULL,
 route TEXT, level INTEGER NOT NULL DEFAULT 0, karma INTEGER NOT NULL DEFAULT 0,
 hunger INTEGER NOT NULL DEFAULT 100 CHECK(hunger BETWEEN 0 AND 100),
 silver INTEGER NOT NULL DEFAULT 30 CHECK(silver>=0), potential INTEGER NOT NULL DEFAULT 0 CHECK(potential>=0),
 first_defeat INTEGER NOT NULL DEFAULT 0, first_win_at REAL, meditate_at REAL,
 next_state TEXT NOT NULL DEFAULT 'unopened', stage_at REAL, defeated INTEGER NOT NULL DEFAULT 0,
 ending TEXT, completed_at REAL, PRIMARY KEY(grp,member)
);
CREATE TABLE IF NOT EXISTS jh_events (
 grp TEXT NOT NULL, member TEXT NOT NULL, chapter INTEGER NOT NULL, event_type TEXT NOT NULL,
 source_event TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(grp,member,chapter,event_type)
);
CREATE TABLE IF NOT EXISTS jh_invites (
 grp TEXT NOT NULL REFERENCES groups, inviter TEXT NOT NULL, invitee TEXT NOT NULL, expires REAL NOT NULL,
 PRIMARY KEY(grp,inviter), UNIQUE(grp,invitee), CHECK(inviter<>invitee)
);
CREATE TABLE IF NOT EXISTS jh_invite_mentions (
 biz TEXT PRIMARY KEY REFERENCES fishing_reply_mentions(biz) ON DELETE CASCADE,
 invitee TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jh_replies (
 task INTEGER PRIMARY KEY REFERENCES outbox(id) ON DELETE CASCADE, version INTEGER NOT NULL
);

-- 第一章通关后按需创建扩展档案；既有角色、鱼币和积分无需搬迁。
CREATE TABLE IF NOT EXISTS jh_world (
 grp TEXT NOT NULL, member TEXT NOT NULL, born REAL NOT NULL,
 stage INTEGER NOT NULL DEFAULT 0, faction TEXT NOT NULL DEFAULT '', cycles INTEGER NOT NULL DEFAULT 0,
 gold INTEGER NOT NULL DEFAULT 0 CHECK(gold>=0), escort REAL, patrol REAL,
 house INTEGER NOT NULL DEFAULT 0, house_day TEXT, pvp INTEGER NOT NULL DEFAULT 0,
 protected REAL NOT NULL DEFAULT 0, inner_art TEXT NOT NULL DEFAULT '', outer_art TEXT NOT NULL DEFAULT '',
 inner_level INTEGER NOT NULL DEFAULT 0, outer_level INTEGER NOT NULL DEFAULT 0,
 ward INTEGER NOT NULL DEFAULT 0, pill INTEGER NOT NULL DEFAULT 0, respec INTEGER NOT NULL DEFAULT 0,
 training TEXT NOT NULL DEFAULT '', mercy INTEGER NOT NULL DEFAULT 0, looks INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(grp,member), FOREIGN KEY(grp,member) REFERENCES jh_players(grp,member)
);
CREATE TABLE IF NOT EXISTS jh_goods (
 id INTEGER PRIMARY KEY, grp TEXT NOT NULL, member TEXT NOT NULL, name TEXT NOT NULL,
 power INTEGER NOT NULL DEFAULT 0, guard INTEGER NOT NULL DEFAULT 0, equipped INTEGER NOT NULL DEFAULT 0,
 price INTEGER NOT NULL DEFAULT 0 CHECK(price>=0), FOREIGN KEY(grp,member) REFERENCES jh_players(grp,member)
);
CREATE INDEX IF NOT EXISTS jh_goods_owner ON jh_goods(grp,member);
CREATE INDEX IF NOT EXISTS jh_market ON jh_goods(grp,price) WHERE price>0;
CREATE UNIQUE INDEX IF NOT EXISTS jh_equipped ON jh_goods(grp,member) WHERE equipped=1;
CREATE TABLE IF NOT EXISTS jh_contracts (
 id INTEGER PRIMARY KEY, grp TEXT NOT NULL, member TEXT NOT NULL, target TEXT NOT NULL,
 amount INTEGER NOT NULL CHECK(amount>0), created REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS jh_contract_owner ON jh_contracts(grp,member);
CREATE INDEX IF NOT EXISTS jh_contract_target ON jh_contracts(grp,target);
CREATE TABLE IF NOT EXISTS jh_relations (
 grp TEXT NOT NULL, kind TEXT NOT NULL, inviter TEXT NOT NULL, invitee TEXT NOT NULL,
 accepted INTEGER NOT NULL DEFAULT 0, expires REAL NOT NULL, PRIMARY KEY(grp,kind,invitee)
);
CREATE INDEX IF NOT EXISTS jh_relation_out ON jh_relations(grp,kind,inviter);
CREATE TABLE IF NOT EXISTS jh_encounters (
 grp TEXT NOT NULL, activity TEXT NOT NULL, period TEXT NOT NULL, member TEXT NOT NULL,
 score INTEGER NOT NULL, last_action REAL NOT NULL, side TEXT NOT NULL DEFAULT '', claimed INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(grp,activity,period,member)
);
CREATE TABLE IF NOT EXISTS jh_money_log (
 id INTEGER PRIMARY KEY, grp TEXT NOT NULL, member TEXT NOT NULL, source TEXT NOT NULL,
 reason TEXT NOT NULL, silver INTEGER NOT NULL, gold INTEGER NOT NULL, at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jh_money_owner ON jh_money_log(grp,member,id);
CREATE TABLE IF NOT EXISTS jh_packets (
 id INTEGER PRIMARY KEY, grp TEXT NOT NULL, sender TEXT NOT NULL, remaining INTEGER NOT NULL CHECK(remaining>=0)
);
CREATE TABLE IF NOT EXISTS jh_packet_claims (
 packet INTEGER NOT NULL REFERENCES jh_packets, member TEXT NOT NULL, PRIMARY KEY(packet,member)
);
CREATE TABLE IF NOT EXISTS jh_strikes (
 grp TEXT NOT NULL, attacker TEXT NOT NULL, victim TEXT NOT NULL, at REAL NOT NULL, won INTEGER NOT NULL,
 PRIMARY KEY(grp,attacker,victim)
);
