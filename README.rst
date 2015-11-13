Jabber Client daemon (jabclnd)
==============================

Jabber Client daemon (jabclnd) is a simple service for sending and receiving
XMPP messages from/to a SQL database. It uses PostgreSQL as its backend
database. It's also build on Twisted framework, so to run it you need twistd
daemon.


Requirements
------------
* Twisted
* PostgreSQL
* psycopg2
* txpostgres
* wokkel


Installation on Debian
----------------------

If you're using Debian Linux system you can install jabclnd deb package
and then jabclnd will be started using the provided init.d script. Setup a
database (see below) using db.sql file and adjust configuration in the
/etc/jabclnd/jabclnd.conf file. Restart jabclnd in order to activate your
configuration. You can find db.sql file in /usr/share/doc/jabclnd/sql
directory after deb package installation.

Debian package can be found at https://github.com/xanderdin/jabclnd-dist-debian


Installation with PyPi
----------------------

If you're using PyPi then do the following. Unpack jabclnd-VERSION.tar.gz to
a temporary directory. Setup a database (see below) using sql/db.sql file.
Install jabclnd requirements:

  pip install -r requirements.txt

Install jabclnd package:

  pip install jabclnd-VERSION.tar.gz

You need to place configuration file cfg/jabclnd.conf manually to a preferred
location. Adjust it as needed and after that you can start jabclnd:

  twistd jabclnd -c path_to_your/jabclnd.conf


Database setup
--------------
Create a database (ex.: jabclnd), connect to it and execute commands from
db.sql file. This will add new database user 'jabclnd' and create a
database structure. Don't forget to change 'jabclnd' user password to you
own secret and set that secret as the database password in jabclnd.conf
configuration file.


Adding XMPP account
-------------------
Add to *xmpp_accounts* database table your XMPP account credentials. You can
add multiple accounts to the *xmpp_accounts* table but only one of them can
be enabled as a working one. The daemon automatically notices changes to this
table and acts accordingly. Example:

  insert into xmpp_accounts (enabled, acc_jid, acc_pass, srv_host)
  values (TRUE, 'username@server', 'mysecret', 'server-ip-or-domain');

Fields of the *xmpp_accounts* table:

:enabled:
  If set to TRUE, the XMPP account credentials from this record
  will be used for connection.

:acc_jid:
  Account JID, ex.: username@server

:acc_pass:
  Account password (plaintext) for connecting to XMPP server.

:srv_host:
  XMPP server host address or domain name. It could be omitted if it is the
  same as in JID.

:port:
  XMPP server port (default 5222).


Sending messages
----------------
In order to send a message add it to *xmpp_tx_queue* database table. Example:

  insert into xmpp_tx_queue (message_to, message_body)
  values ('someuser@someserver', 'Hello, there!');

Fields of the *xmpp_tx_queue* table:

:insert_timestamp:
  Timestamp of when the message was added. This is set automatically,
  you don't need to set it.

:message_stanza:
  You can put here your message XML stanza. If this field is filled
  then other message_* fields are not used for message sending.

:message_to:
  Recipient address (JID).

:message_subject:
  Message subject text.

:message_body:
  Body part of the message (usually a text)

:submission_timestamp:
  Timestamp of when the message was sent. This field is set
  by the jabclnd. Do not set this field yourself.

:submission_failed:
  Set by jabclnd to TRUE when it failed to send the message to XMPP server.
  Do not set this field yourself.

:submission_info:
  This could be filled by jabclnd with some error information on sending
  failure. Do not set this field yourself.


Receiving messages
------------------
Incoming messages are saved to *xmpp_rx_queue** table.

Fields of the *xmpp_rx_queue* table:

:insert_timestamp:
  Timestamp of when the message was received.

:message_stanza:
  Full received XML message stanza.

:message_from:
  Sender's address (JID).

:message_subject:
  Message subject text.

:message_body:
  Body part of the message (usually a text)


Openfire XMPP server users integration
--------------------------------------
If you want you can setup Openfire server to get its users from jabclnd
database. For this purpose there is *openfire_users* table present and
also *openfire_users_view* view. The *openfire_users_view* allows you
to enter jabclnd user credentials only once (in xmpp_accounts table only).
For setup procedure please read README file in openfire directory.

Fields of *openfire_users* table:

:login:
  User login.

:pass:
  User password as MD5 hash. Use md5() PostgreSQL function for setting it.

:enabled:
  Enable/disable this user.

:name:
  User name.

:email:
  User email.

:available:
  User presence. Set by jabclnd.

:available_timestamp:
  The available field change time. Set by jabclnd.

Example of adding users to openfire_users table:

  insert into openfire_users (login, pass, enabled)
  values ('someuser', md5('somepassword'), TRUE);