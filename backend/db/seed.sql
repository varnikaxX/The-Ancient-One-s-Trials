-- seed.sql : demo data. All demo accounts use the password  Passw0rd!
-- (hashes below are argon2id; regenerate with `python db/make_seed_hashes.py`)

INSERT INTO users (id, name, email, password_hash, role) VALUES
 (1, 'Wong (Coordinator)',  'coordinator@trials.edu', '$argon2id$v=19$m=19456,t=2,p=1$bHbuqTYg7crFFgNtnhby2w$DeP9RovD970W1s41/7xMre/a91yoxtGv45vIcfRFkQY', 'COORDINATOR'),
 (2, 'Arjun Mehta',         'arjun@kamartaj.com',     '$argon2id$v=19$m=19456,t=2,p=1$lftJYZhgCiAkXsGMbf96Dg$JTeeRvBb4o+fBxmTjr3RBVHLGhBNPq7Nx2gMPf4yFjc', 'INTERVIEWER'),
 (3, 'Meera Kapoor',        'meera@kamartaj.com',     '$argon2id$v=19$m=19456,t=2,p=1$jCxSm4TS7w9AcmlRDnlGSw$lI0EWaKV69DTq4gQLBq+BNmaEidk5vi9V4d1k3g6xaM', 'INTERVIEWER'),
 (4, 'Kabir Sinha',         'kabir@sanctum.io',       '$argon2id$v=19$m=19456,t=2,p=1$aWcdHZaOGv6gRmcnO2iZHA$UoUm5CxYwJSOSaODujYsok8DciZnlK7rQwoEtykP89I', 'INTERVIEWER');
SELECT setval('users_id_seq', 100);

INSERT INTO companies (id, name, rounds_config, panel_skills) VALUES
 (1, 'Kamar-Taj Labs',  '[{"roundNo":1,"name":"Coding"},{"roundNo":2,"name":"Tech"},{"roundNo":3,"name":"HR"}]', '{Coding,Tech}'),
 (2, 'Sanctum Systems', '[{"roundNo":1,"name":"Coding"},{"roundNo":2,"name":"Tech"},{"roundNo":3,"name":"HR"}]', '{Coding,HR}');
SELECT setval('companies_id_seq', 100);

INSERT INTO interviewers (user_id, company_id, skill_tags, is_active) VALUES
 (2, 1, '{Coding,Tech}', true),
 (3, 1, '{Coding,HR}',   true),
 (4, 2, '{Coding,Tech,HR}', true);

INSERT INTO rooms (id, name, capacity) VALUES
 (1, 'Sanctum Hall',   2),
 (2, 'Mirror Chamber', 2),
 (3, 'Library of Cagliostro', 4);
SELECT setval('rooms_id_seq', 100);

INSERT INTO config (key, value) VALUES ('result_delay_minutes', '0')
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

-- Sample slots: 2026-11-03, 09:00-11:00 UTC, 30 minutes each, one room per interviewer.
INSERT INTO availability_slots (interviewer_id, start_ts, end_ts, status, room_id)
SELECT i.uid,
       ts,
       ts + interval '30 minutes',
       'FREE',
       i.room
FROM (VALUES (2, 1), (3, 2), (4, 3)) AS i(uid, room),
     generate_series(timestamptz '2026-11-03 09:00:00+00',
                     timestamptz '2026-11-03 10:30:00+00',
                     interval '30 minutes') AS ts;
