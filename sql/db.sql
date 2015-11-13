--
--   Copyright 2015 Alexander Pravdin <aledin@mail.ru>
--
--   Licensed under the Apache License, Version 2.0 (the "License");
--   you may not use this file except in compliance with the License.
--   You may obtain a copy of the License at
--
--       http://www.apache.org/licenses/LICENSE-2.0
--
--   Unless required by applicable law or agreed to in writing, software
--   distributed under the License is distributed on an "AS IS" BASIS,
--   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
--   See the License for the specific language governing permissions and
--   limitations under the License.
--


-- Creating user role for the daemon.
-- Don't forget to change the password to your own secret
-- after creating this user role!!!
CREATE ROLE jabclnd LOGIN
    ENCRYPTED PASSWORD 'md5dc03442517e77aed9f84185ef9fed65f'
    NOSUPERUSER INHERIT NOCREATEDB NOCREATEROLE;


-- Trigger function to keep only one XMPP account enabled.
CREATE OR REPLACE FUNCTION only_one_enabled() RETURNS trigger AS $BODY$

begin
	if TG_OP = 'DELETE' then
		return OLD;
	end if;

	if NEW.enabled = TRUE then
		EXECUTE 'UPDATE ' || TG_TABLE_NAME || ' SET enabled = FALSE WHERE id != ' || NEW.id;
	end if;

	return NEW;
end;

$BODY$ LANGUAGE plpgsql;


-- Trigger function for dispatching notification events
-- To use it just create a trigger for the needed table
-- and set trigger's EXECUTE PROCEDURE to this function.
-- Notifications will contain that table name.
CREATE OR REPLACE FUNCTION notify_table_change() RETURNS trigger AS $BODY$

begin
	perform pg_notify('notify_table_change', TG_TABLE_NAME);

	if TG_OP = 'DELETE' then
		return OLD;
	end if;

	return NEW;
end;

$BODY$ LANGUAGE plpgsql STABLE;


-- XMPP accounts related configuration
CREATE TABLE xmpp_accounts
(
    id SERIAL PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    acc_jid CHARACTER VARYING(255) NOT NULL,              -- JID
    acc_pass CHARACTER VARYING NOT NULL,                  -- Password
    srv_host CHARACTER VARYING NOT NULL DEFAULT '',       -- XMPP server host
    srv_port INTEGER NOT NULL DEFAULT 5222,               -- XMPP server port
    CONSTRAINT xmpp_accounts_ukey1 UNIQUE (acc_jid, srv_host, srv_port)
);

-- XMPP queue for transmission
CREATE TABLE xmpp_tx_queue
(
    id SERIAL PRIMARY KEY,
    insert_timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    message_stanza CHARACTER VARYING,                     -- XML message stanza (if used, overrides other message_* fields)
    message_to CHARACTER VARYING(255),                    -- recipient's JID
    message_subject CHARACTER VARYING,                    -- message subject
    message_body CHARACTER VARYING,                       -- message body
    submission_timestamp TIMESTAMP WITH TIME ZONE NULL,   -- timestamp of when we submitted the message
    submission_failed BOOLEAN NOT NULL DEFAULT FALSE,     -- if an error occurred
    submission_info CHARACTER VARYING                     -- this could be the error message when submission_failed is set to TRUE
);

-- XMPP received messages queue
CREATE TABLE xmpp_rx_queue
(
    id SERIAL PRIMARY KEY,
    insert_timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    message_stanza CHARACTER VARYING,                      -- XML message stanza
    message_from CHARACTER VARYING,                        -- message sender's JID
    message_subject CHARACTER VARYING,                     -- message subject
    message_body CHARACTER VARYING                         -- message body
);


-- Openfire users table
-- Used for Openfire integration
CREATE TABLE openfire_users
(
    login CHARACTER VARYING NOT NULL,                      -- login
    pass CHARACTER VARYING,                                -- password
    enabled BOOLEAN NOT NULL DEFAULT FALSE,                -- enabled/disabled flag
    name CHARACTER VARYING,                                -- user name
    email CHARACTER VARYING,                               -- email address
    available BOOLEAN NOT NULL DEFAULT FALSE,              -- is contact available now
    available_timestamp TIMESTAMP WITH TIME ZONE,          -- time of when available field was changed
    CONSTRAINT web_users_pkey PRIMARY KEY (login)
);


-- A view to provide the Openfire with users.
-- The Openfire requires the following fields:
-- username, password, name, email.
CREATE OR REPLACE VIEW openfire_users_view AS
    -- From openfire_users table
    SELECT
        lower(openfire_users.login) AS username,
        openfire_users.pass AS password,
        openfire_users.name,
        openfire_users.email
    FROM openfire_users
    WHERE NOT EXISTS ( -- Do not include users which exist in xmpp_accounts table.
        SELECT 1
        FROM xmpp_accounts
            WHERE lower(split_part(xmpp_accounts.acc_jid, '@', 1)) = lower(openfire_users.login)
            AND xmpp_accounts.enabled = TRUE
            AND xmpp_accounts.acc_pass IS NOT NULL
            AND TRIM(xmpp_accounts.acc_pass) <> '')
    AND openfire_users.enabled = TRUE
    AND openfire_users.pass IS NOT NULL
    AND TRIM(openfire_users.pass) <> ''
UNION
    -- From xmpp_accounts table
    SELECT
        lower(split_part(xmpp_accounts.acc_jid, '@', 1)) AS username,
        md5(xmpp_accounts.acc_pass) AS password,
        xmpp_accounts.acc_jid AS name,
        NULL AS email
    FROM xmpp_accounts
    WHERE xmpp_accounts.enabled = TRUE
    AND xmpp_accounts.acc_pass IS NOT NULL
    AND TRIM(xmpp_accounts.acc_pass) <> '';


CREATE TRIGGER xmpp_accounts_only_one_enabled
    AFTER INSERT OR UPDATE
    ON xmpp_accounts
    FOR EACH ROW
    EXECUTE PROCEDURE only_one_enabled();


CREATE TRIGGER xmpp_accounts_notify_change
    AFTER INSERT OR UPDATE OR DELETE
    ON xmpp_accounts
    FOR EACH ROW
    EXECUTE PROCEDURE notify_table_change();


CREATE TRIGGER xmpp_tx_queue_notify_change
    AFTER INSERT
    ON xmpp_tx_queue
    FOR EACH ROW
    EXECUTE PROCEDURE notify_table_change();


GRANT SELECT ON TABLE xmpp_accounts TO jabclnd;

GRANT SELECT, UPDATE ON TABLE xmpp_tx_queue TO jabclnd;

GRANT INSERT ON TABLE xmpp_rx_queue TO jabclnd;

GRANT SELECT,UPDATE ON SEQUENCE xmpp_rx_queue_id_seq TO jabclnd;

GRANT SELECT,UPDATE ON TABLE openfire_users TO jabclnd;

GRANT SELECT ON TABLE openfire_users_view TO jabclnd;
