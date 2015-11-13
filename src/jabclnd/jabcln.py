#
#   Copyright 2015 Alexander Pravdin <aledin@mail.ru>
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#

import logging

from twisted.application import service
from twisted.internet import task, reactor
from twisted.words.protocols.jabber.jid import JID
from twisted.words.xish import domish

from txpostgres import txpostgres, reconnection

from wokkel import client, xmppim
from wokkel.subprotocols import XMPPHandler, IQHandlerMixin

# In order to force UTF-8 data work correctly
import sys
reload(sys)
sys.setdefaultencoding('UTF-8')


__author__ = 'Alexander Pravdin <aledin@mail.ru>'


XPATH_IQ_PING = "/iq[@type='get']/ping[@xmlns='urn:xmpp:ping']"


CFG_DB_HOST = 'host'
CFG_DB_PORT = 'port'
CFG_DB_NAME = 'name'
CFG_DB_USER = 'user'
CFG_DB_PASS = 'pass'
CFG_DB_SSL_MODE = 'sslmode'


FLD_ACC_JID = 'acc_jid'
FLD_ACC_PASS = 'acc_pass'
FLD_SRV_HOST = 'srv_host'
FLD_SRV_PORT = 'srv_port'


xmpp_acc_query_fields_list = [
    FLD_ACC_JID,
    FLD_ACC_PASS,
    FLD_SRV_HOST,
    FLD_SRV_PORT,
]


def get_db_config_dict(config, section):

    r = {
        CFG_DB_HOST: 'localhost',
        CFG_DB_PORT: '5432',
        CFG_DB_NAME: 'jabclnd',
        CFG_DB_USER: 'jabclnd',
        CFG_DB_PASS: 'pass',
        CFG_DB_SSL_MODE: 'disable',
    }

    for k in r.keys():
        if config.has_option(section, k):
            r[k] = config.get(section, k)

    return r


def make_xmpp_acc_conf_dict(db_result_row):
    """
    Construct a XMPP accounts configuration dictionary from DB result row
    :param db_result_row: DB result row
    :return: XMPP accounts configuration dictionary
    """
    res = dict()
    for v in xmpp_acc_query_fields_list:
        res[v] = db_result_row[xmpp_acc_query_fields_list.index(v)]
    return res


class Db:

    def __init__(self, config, section, detector):
        """
        Db
        :param config: L{ConfigParser} object
        :param section: Config file section name with settings for this Db
        :param detector: L{txpostgres.reconnection.DeadConnectionDetector} object
        """
        self.conf = get_db_config_dict(config, section)
        self.conn = txpostgres.Connection(detector=detector)

    def connect(self):
        d = self.conn.connect(host=self.conf[CFG_DB_HOST],
                              port=self.conf[CFG_DB_PORT],
                              user=self.conf[CFG_DB_USER],
                              password=self.conf[CFG_DB_PASS],
                              database=self.conf[CFG_DB_NAME],
                              sslmode=self.conf[CFG_DB_SSL_MODE])
        d.addErrback(self.conn.detector.checkForDeadConnection)
        return d


class DbDetector(reconnection.DeadConnectionDetector):
    """
    Object of this class performs needed actions on
    database reconnection events.
    """
    def __init__(self, caller_service):
        super(DbDetector, self).__init__()
        self.service = caller_service

    def startReconnecting(self, f):
        self.service.on_db_disconnected()
        return reconnection.DeadConnectionDetector.startReconnecting(self, f)

    def reconnect(self):
        self.service.on_db_reconnect()
        return reconnection.DeadConnectionDetector.reconnect(self)

    def connectionRecovered(self):
        self.service.on_db_connected(None)
        return reconnection.DeadConnectionDetector.connectionRecovered(self)


class ElementParser(object):
    """
    Callable class to parse XML string into Element
    """
    def __call__(self, s):
        self.result = None

        def onStart(el):
            self.result = el

        def onEnd():
            pass

        def onElement(el):
            self.result.addChild(el)

        parser = domish.elementStream()

        parser.DocumentStartEvent = onStart
        parser.ElementEvent = onElement
        parser.DocumentEndEvent = onEnd

        tmp = domish.Element(("", "s"))
        tmp.addRawXml(s)

        parser.parse(tmp.toXml())

        return self.result.firstChildElement()


class JabPresenceHandler(xmppim.PresenceProtocol):
    """
    Presence accepting XMPP subprotocol handler.

    This handler blindly accepts incoming presence subscription requests,
    confirms unsubscription requests and responds to presence probes.

    Note that this handler does not remember any contacts, so it will not
    send presence when starting.
    """
    def __init__(self, db, roster_handler):
        super(JabPresenceHandler, self).__init__()
        self.log = logging.getLogger(__name__)
        self.my_status = u"I'm here"
        self.db = db
        self.roster_handler = roster_handler

    def subscribedReceived(self, presence):
        """
        Subscription approval confirmation was received.

        This is just a confirmation. Don't respond.
        """
        pass

    def unsubscribedReceived(self, presence):
        """
        Unsubscription confirmation was received.

        This is just a confirmation. Don't respond.
        """
        pass

    def subscribeReceived(self, presence):
        """
        Subscription request was received.

        Always grant permission to see our presence.
        """
        self.subscribed(recipient=presence.sender,
                        sender=presence.recipient)
        self.available(recipient=presence.sender,
                       status=self.my_status,
                       sender=presence.recipient)
        self.subscribe(recipient=presence.sender,
                       sender=presence.recipient)

    def unsubscribeReceived(self, presence):
        """
        Unsubscription request was received.

        Always confirm unsubscription requests.
        """
        self.unsubscribed(recipient=presence.sender,
                          sender=presence.recipient)
        d = self.roster_handler.removeItem(presence.sender)
        d.addErrback(lambda _: None)

    def probeReceived(self, presence):
        """
        A presence probe was received.

        Always send available presence to whoever is asking.
        """
        self.available(recipient=presence.sender,
                       status=self.my_status,
                       sender=presence.recipient)

    def availableReceived(self, presence):
        """
        What to do on receiving 'available' presence

        :param presence: L{w.x.AvailabilityPresence}
        """
        self.update_available_status_in_db(presence)

    def unavailableReceived(self, presence):
        """
        What to do on receiving 'unavailable' presence

        :param presence: L{w.x.AvailabilityPresence}
        """
        self.update_available_status_in_db(presence)

    def update_available_status_in_db(self, presence):
        """
        Update user 'connected' status on received presence

        :param presence: L{w.x.AvailabilityPresence}
        """
        q = """
            UPDATE
                openfire_users
            SET
                available = %s,
                available_timestamp = now()
            WHERE
                login = %s
            AND
                enabled = TRUE
            """

        sender_jid = presence.sender.userhost()

        if sender_jid.find('@') < 1:
            return

        login = sender_jid.split('@')[0]
        # login = sender_jid

        d = self.db.conn.runOperation(q, (presence.available, login))

        d.addErrback(self.on_error)

    def on_error(self, e):
        if e is None:
            self.log.error('Error: UNKNOWN')
        else:
            self.log.error('Error: %r' % e.value)


class JabMessageHandler(xmppim.MessageProtocol):
    """
    Message handler
    """
    def __init__(self, db):
        super(JabMessageHandler, self).__init__()
        self.log = logging.getLogger(__name__)
        self.db = db

    def connectionMade(self):
        """
        Called when connection is made
        """
        super(JabMessageHandler, self).connectionMade()
        self.log.info('XMPP connection established')

    def connectionInitialized(self):
        """
        Called on successful login to XMPP server
        """
        super(JabMessageHandler, self).connectionInitialized()
        self.log.info('XMPP connection initialized')
        self.send('<presence/>')
        self.db.conn.addNotifyObserver(self.on_xmpp_tx_queue_table_change)
        self.proc_tx_messages()

    def connectionLost(self, reason):
        """
        Called when connection to XMPP server is lost

        :param reason:
        """
        super(JabMessageHandler, self).connectionLost(reason)
        self.log.info('XMPP connection lost: %r' % reason)
        self.remove_notify_observer()

    def remove_notify_observer(self):
        self.db.conn.removeNotifyObserver(self.on_xmpp_tx_queue_table_change)

    def _onMessage(self, message):
        """
        Override ancestor's _onMessage() in order to react on error

        :param message:
        """

        if message.handled:
            return

        message_type = message.getAttribute('type')

        if message_type != 'error':
            super(JabMessageHandler, self)._onMessage(message);
            return

        if not message.hasAttribute('id'):
            return

        message_id = message.getAttribute('id')

        try:
            id = int(message_id)
        except ValueError:
            return

        q = "UPDATE xmpp_tx_queue SET submission_failed = TRUE, submission_info = %s WHERE id = %s"

        d = self.db.conn.runOperation(q, (message.error.toXml(), id))

        d.addErrback(self.on_error)

    def onMessage(self, message):
        """
        Called when message is received

        :param message: L{xmppim.Message}
        """
        super(JabMessageHandler, self).onMessage(message)
        self.log.debug('RX: %r' % message.toXml())

        # Filter out messages without a type
        if not message.hasAttribute('type'):
            return

        fl = list(['message_stanza'])
        vl = list([message.toXml()])

        if message.hasAttribute('from'):
            fl.append('message_from')
            vl.append(message.getAttribute('from'))
        if message.subject:
            fl.append('message_subject')
            vl.append(''.join(message.subject.children))
        if message.body:
            fl.append('message_body')
            vl.append(''.join(message.body.children))

        ql = list(['INSERT INTO xmpp_rx_queue ('])
        ql.append(','.join(fl))
        ql.append(') VALUES (')
        ql.append(','.join([r'%s' for v in vl]))
        ql.append(')')

        q = ''.join(ql)

        d = self.db.conn.runOperation(q, vl)

        d.addErrback(self.on_error)


    def on_xmpp_tx_queue_table_change(self, notify):
        """
        Things to do on asynchronous notification from DB when xmpp_tx_queue table changes

        :param notify: Notification data
        """
        if not notify.payload:
            return
        if notify.payload == "xmpp_tx_queue":
            self.proc_tx_messages()

    def proc_tx_messages(self):
        """
        Get unsent messages from DB and put them to sending method

        :return: L{Deferred} query result with list of unsent messages
        """
        q = """
            SELECT
                id,
                insert_timestamp,
                message_stanza,
                message_to,
                message_subject,
                message_body
            FROM xmpp_tx_queue
                WHERE submission_timestamp IS NULL
                    ORDER BY id
        """
        d = self.db.conn.runQuery(q)
        d.addCallbacks(self.send_messages, self.on_error)
        return d

    def send_messages(self, messages_list):
        """
        Send messages from resulting DB list of unsent messages

        :param messages_list: list of unsent messages
        """
        if not messages_list:
            # nothing to send
            return

        # if send operation would fail the next line
        # would give a chance to try it again
        reactor.callLater(5, self.proc_tx_messages)

        dl = list()

        for msg in messages_list:
            id, insert_timestamp, message_stanza, message_to, message_subject, message_body = msg

            if message_stanza:
                message_stanza = ElementParser()(message_stanza)
            else:
                m = xmppim.Message(recipient=JID(message_to), subject=message_subject, body=message_body)
                message_stanza = m.toElement()
                message_stanza['type'] = 'normal'
                message_stanza['id'] = str(id)

            self.log.debug('%r' % message_stanza.toXml())

            self.send(message_stanza)

            q = "UPDATE xmpp_tx_queue SET submission_timestamp = now()"
            d = self.db.conn.runOperation(q)
            d.addErrback(self.on_error)
            dl.append(d)

    def on_error(self, e):
        if e is None:
            self.log.error('Error: UNKNOWN')
        else:
            self.log.error('Error: %r' % e.value)


class JabPingHandler(XMPPHandler, IQHandlerMixin):
    """
    A handler to response to pings from XMPP server
    """
    iqHandlers = {XPATH_IQ_PING: 'onPing',}

    def connectionMade(self):
        self.xmlstream.addObserver(XPATH_IQ_PING, self.handleRequest)

    def onPing(self, iq):
        # No need to enter anything here. Wokkel
        # works instead of me. BUT DO NOT DELETE
        # THIS CODE!!! Or Wokkel won't send
        # ping responses.
        pass


class JabClnService(service.MultiService):
    """
    Object of this class will act as twisted service.
    """

    def __init__(self, config):
        # super(JabClnService, self).__init__()
        service.MultiService.__init__(self)
        self.log = logging.getLogger(__name__)
        self.config = config
        self.db = None
        self.db_checker_loop = None
        self.srv_host = None
        self.srv_port = None
        self.acc_jid = None
        self.acc_pass = None
        self.client_service = None
        self.roster_handler = None
        self.presence_handler = None
        self.message_handler = None
        self.xmpp_acc_conf_dict = None
        self.ping_handler = None

    def startService(self):
        self.log.info('Started')
        self.db = Db(self.config, 'database', DbDetector(self))
        self.log.info('Connecting to DB...')
        d = self.db.connect()
        d.addCallbacks(self.on_db_connected, self.on_error)

    def stopService(self):
        self.log.info('Exiting...')
        d = service.Service.stopService(self)
        if d is None:
            self.on_service_stopped()
        else:
            d.addCallbacks(self.on_service_stopped, self.on_error)

    def on_service_stopped(self, _=None):
        self.log.info('Bye.')

    def on_db_connected(self, _):
        self.log.info('Connected to DB')
        self.db_checker_loop = task.LoopingCall(self.check_db_conn)
        self.db_checker_loop.start(5)

    def check_db_conn(self):
        self.log.info('Checking DB connection...')
        d = self.db.conn.runQuery('SELECT 1')
        d.addCallbacks(self.on_db_conn_ok, self.on_error)

    def on_db_conn_ok(self, _):
        self.log.info('DB connection is OK')
        self.db_checker_loop.stop()
        self.db_checker_loop = None
        self.load_jab_client()

    def on_db_reconnect(self):
        self.log.info('Reconnecting to DB...')

    def on_db_disconnected(self):
        self.log.info('Disconnected from DB')
        if self.db_checker_loop:
            self.db_checker_loop.stop()
            self.db_checker_loop = None
        self.drop_jab_client()

    def load_jab_client(self):
        d = self.run_xmpp_accounts_query()
        d.addCallbacks(self.run_jab_client, self.on_error)
        self.db.conn.addNotifyObserver(self.on_xmpp_accounts_table_change)
        d.addCallbacks(lambda _: self.db.conn.runOperation('LISTEN notify_table_change'), self.on_error)

    def on_xmpp_accounts_table_change(self, notify):
        """
        React on asynchronous notification from DB

        :param notify: notification data
        """
        if notify.payload == "xmpp_accounts":
            d = self.run_xmpp_accounts_query()
            d.addCallbacks(self.restart_jab_client, self.on_error)

    def run_xmpp_accounts_query(self):
        """
        Get configuration for XMPP accounts from DB

        :return: L{Deferred} for the query result
        """
        ql = list(["SELECT"])
        ql.append(", ".join(xmpp_acc_query_fields_list))
        ql.append("FROM xmpp_accounts WHERE enabled IS TRUE")
        ql.append("AND TRIM(acc_jid) <> ''")
        ql.append("LIMIT 1")
        q = " ".join(ql)
        d = self.db.conn.runQuery(q)
        return d

    def run_jab_client(self, xmpp_acc_list):
        """
        Prepare and start a client instance

        :param xmpp_acc_list: A list of query results from xmpp_accounts table.
        """
        if not xmpp_acc_list:
            return
        self.do_jab_client(make_xmpp_acc_conf_dict(xmpp_acc_list[0]))

    def do_jab_client(self, xmpp_acc_conf_dict):

        if self.client_service is not None:
            return

        self.xmpp_acc_conf_dict = xmpp_acc_conf_dict
        self.srv_host = xmpp_acc_conf_dict[FLD_SRV_HOST]
        self.srv_port = xmpp_acc_conf_dict[FLD_SRV_PORT]
        self.acc_jid = JID(xmpp_acc_conf_dict[FLD_ACC_JID])
        self.acc_pass = xmpp_acc_conf_dict[FLD_ACC_PASS]
        self.client_service = client.XMPPClient(self.acc_jid, self.acc_pass, self.srv_host, self.srv_port)
        if self.log.getEffectiveLevel() == logging.DEBUG:
            self.client_service.logTraffic = True
        self.client_service.setServiceParent(self)
        self.ping_handler = JabPingHandler()
        self.ping_handler.setHandlerParent(self.client_service)
        self.roster_handler = xmppim.RosterClientProtocol()
        self.roster_handler.setHandlerParent(self.client_service)
        self.presence_handler = JabPresenceHandler(self.db, self.roster_handler)
        self.presence_handler.setHandlerParent(self.client_service)
        self.message_handler = JabMessageHandler(self.db)
        self.message_handler.setHandlerParent(self.client_service)
        self.client_service.startService()

    def drop_jab_client(self):
        """
        Shut down client's connection to XMPP server and initiate JabClient object deletion.
        """
        if self.client_service is None:
            return

        self.client_service.stopService()
        self.presence_handler.disownHandlerParent(self.client_service)
        self.roster_handler.disownHandlerParent(self.client_service)
        self.ping_handler.disownHandlerParent(self.client_service)
        self.message_handler.remove_notify_observer()
        self.message_handler.disownHandlerParent(self.client_service)
        self.client_service.disownServiceParent()
        self.client_service = self.message_handler = self.ping_handler = None
        self.presence_handler = self.roster_handler = None
        self.srv_host = self.srv_port = self.acc_jid = self.acc_pass = None
        self.xmpp_acc_conf_dict = None

    def restart_jab_client(self, xmpp_acc_list):
        """
        Restart a client

        :param xmpp_acc_list: A list of query results from xmpp_accounts table.
        """
        if not xmpp_acc_list:
            # no accounts in DB, stop client and don't restart it
            self.drop_jab_client()
            return
        xmpp_acc_conf_dict = make_xmpp_acc_conf_dict(xmpp_acc_list[0])
        if xmpp_acc_conf_dict == self.xmpp_acc_conf_dict:
            # configuration not changed, do not restart
            return
        self.drop_jab_client()
        self.do_jab_client(xmpp_acc_conf_dict)

    def on_error(self, e):
        if e is None:
            self.log.error('Error: UNKNOWN')
        else:
            self.log.error('Error: %r' % e.value)
