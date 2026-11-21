# Security FAQ: API key rotation

Source: slack

Pinned in #security-help by the security team.

Q: How do I rotate the key?
A: Open the credentials page in the admin console, create a new key, deploy it to every service that reads the old one, then revoke the old key.

Q: Who approves?
A: The service owner approves a routine rotation; an emergency rotation after a leak is approved by the security on-call engineer.
