# Security policy

## Supported versions

Only the latest release of drishya gets fixes.

## Reporting a vulnerability

Please **don't open a public issue**. Report it privately through
[GitHub's security advisories](https://github.com/Theyashsawarkar/drishya/security/advisories/new),
with what an attacker could do and how to reproduce it. You'll get a reply
within a week; a fix and a release follow as soon as it's confirmed, with
credit to you unless you'd rather not.

drishya runs as your user. It plays what you open (through libmpv and
yt-dlp) and talks to YouTube and the servers you play from. Logins you type
are sent only to the server that asked for them, kept in memory, or in your
keyring (libsecret) when you ask; they're never logged or written to its
own files, and credentials in a link are removed before the link is saved.
Especially in scope: anything that sends a login to another server, writes
it to disk, or lets a link or a stream run code.
