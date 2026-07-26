# Skill registry policy

## Operator Configured Rules

1. For skills discovery/install/update, try `skillhub` first (cn-optimized).
2. If unavailable, rate-limited, or no match, fallback to `clawhub` (public-registry).
3. Do not claim exclusivity. Public and private registries are both allowed.
4. Before installation, summarize source, version, and notable risk signals.
5. For search requests, execute `exec` with `skillhub search <keywords>` first and report the command output.
6. In the current session, reply directly. Do NOT call `message` tool just to send progress updates.

## Conversation Info (Untrusted Metadata)

```json
{
  "message_id": "2313",
  "sender_id": "2033937852",
  "sender": "Shengyu Li",
  "timestamp": "Thu 2026-03-12 22:06 GMT+8",
  "topic_id": "11606"
}
```

## Sender (Untrusted Metadata)

```json
{
  "label": "Shengyu Li (2033937852)",
  "id": "2033937852",
  "name": "Shengyu Li",
  "username": "KCNyu"
}
```
