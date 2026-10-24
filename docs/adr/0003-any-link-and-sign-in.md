# 3. Any link plays, and logins stay out of files

**Status:** Accepted  
**Date:** 2026-10-24

## Context

Videos aren't only on YouTube: HLS streams on a company's server, a file on a home server, other sites. Some need a login.

## Decision

Any link is a queue item that mpv opens (ffmpeg for streams and files, yt-dlp for sites). When mpv reports a 401 or 403 (or yt-dlp says it needs an account), drishya asks for a login and retries: HTTP Basic as a header on every request (HLS segments included) plus the login in the link for Digest, or yt-dlp's username and password, or the browser's cookies. Logins live in memory, or in the keyring through libsecret when asked; credentials typed into a link are taken out of it before it's stored anywhere.

## Consequences

- drishya never writes a password to its own files or logs.
- A login is per server (scheme, host, port), so every stream on that server uses it.
