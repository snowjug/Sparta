# Android SIP testing (Linphone and Sparta over local SIP)

**Status: a checklist for a physical-phone test. It has NOT been run on a physical phone.** What has been verified is the
server side with a headless SIP client in Docker (see [PHASE3_ASTERISK_PLAN.md](PHASE3_ASTERISK_PLAN.md) and
[TELEPHONY.md](TELEPHONY.md)). Every phone-specific statement below comes from Linphone's source and documentation, not from a
run on a device, and is marked where it matters.

**What this is, and is not.** A SIP phone on your own Wi-Fi calls extension 6000 and talks to Sparta in both directions.
It is a *local VoIP* call. It is **not** a call over the mobile network: a friend dialling your ordinary phone number cannot
reach Sparta this way. That needs a paid carrier, a phone number and a SIP trunk, which Sparta does not provide and this
phase does not deliver.

## 1. What you need

* A computer running the stack: `docker compose --profile asterisk up --build` (see the README section "Run Sparta voice locally
  without Twilio").
* An Android phone on the **same Wi-Fi network** as that computer, with no "client isolation" (guest networks often have it).
* The open-source **Linphone** app (Belledonne Communications, GPLv3): Google Play, or F-Droid (which carries an older build).
  Any maintained SIP client works; baresip for Android (BSD) is an alternative.
* The computer's LAN address, for example `192.168.1.20` (Windows: `ipconfig`; Linux/macOS: `ip addr` / `ifconfig`).

## 2. Open the server to the phone (once)

By default Compose publishes SIP and RTP on `127.0.0.1` only, so only a client on the same machine can reach it. For a phone,
put the LAN address in `.env` (both lines), then recreate the container:

```
SPARTA_ASTERISK_BIND=192.168.1.20
SPARTA_ASTERISK_EXTERNAL_IP=192.168.1.20
```

```
docker compose --profile asterisk up -d
```

* `SPARTA_ASTERISK_BIND` is the address the ports are published on; `SPARTA_ASTERISK_EXTERNAL_IP` is the address Asterisk tells
  the phone to send audio to (Docker's own address is not reachable from the phone). Use this computer's one LAN address,
  never `0.0.0.0`, so the ports are not opened on every interface (VPN, hotspot, virtual adapters).
* Allow inbound **UDP 5060** and **UDP 10000-10019** to this computer in its firewall, on the *private* network profile only
  (Windows Defender Firewall prompts for Docker Desktop; allow private networks, not public). If you can, scope the rule to the
  phone's own address.
* Only private networks may talk SIP to Asterisk (`SPARTA_ASTERISK_ALLOWED_NETS`, default RFC 1918 ranges): a phone on a
  public address will be ignored on purpose. That check looks at the packet's source address, and **Docker Desktop (Windows,
  macOS) rewrites the source address of published UDP**, so there it cannot tell a LAN phone from any other sender: the
  firewall scope and the passwords are what protect you. On Linux, with Docker's default networking, the real source address
  is kept and the check is effective.
* Asterisk in this image has **no limit on failed logins** (no fail2ban, no ban list). The generated passwords are 32 random
  characters, which is why that is acceptable on your own network; do not replace them with a short, memorable one (the
  container refuses anything under 24 characters or with fewer than 8 different ones). On a network you do not fully trust, add
  a firewall rule that allows only the phone's address, or run fail2ban on the host against the `Failed to authenticate`
  lines in `docker compose logs asterisk`.

## 3. Get the credentials

```
python scripts/sip_local.py show --reveal
```

It prints the server address, the extensions and (because you asked with `--reveal`) the passwords. They were generated
randomly by `python scripts/sip_local.py init` and live in `.env.sip` (git-ignored). Without `--reveal` the passwords are
hidden. Never paste them into an issue or a chat.

| Extension | Use | Username | Password |
|---|---|---|---|
| 6000 | **Sparta** (the AI call assistant) | not an account: you *dial* it | n/a |
| 6001 | the test caller: **register this one on the phone** | `6001` | `SIP_PASSWORD_6001` |
| 6002 | the owner's phone, rung when you press *Take Over* in the Sparta app | `6002` | `SIP_PASSWORD_6002` |

## 4. Register Linphone as 6001

(From the Linphone 6.x source and documentation; menu wording may differ slightly between versions. **Unverified on a device.**)

1. Open Linphone. In the assistant choose **Use a third party SIP account** (not "Create account": that would use Linphone's own cloud service).
2. Username `6001`, password from `sip_local.py show --reveal`, **Domain** = the server address, for example `192.168.1.20:5060`.
3. **Transport: UDP.** Leave *outbound proxy* empty.
4. After signing in open the account settings and, for this LAN-only test:
   * clear the **STUN server** (the third-party profile pre-fills `stun.linphone.org`) and switch **ICE** and **TURN** off: nothing here needs the internet;
   * leave **SRTP/media encryption** off or "optional" (Asterisk offers plain RTP);
   * under audio codecs keep **PCMU** (G.711 µ-law) and **PCMA** enabled. Opus and G.722 may stay on: Asterisk only accepts G.711, so G.711 is what is used.
5. Keep Linphone in the foreground, or exempt it from Android's battery optimisation (Settings > Apps > Linphone > Battery > Unrestricted), so the registration stays alive.

**Confirm registration.** Linphone shows the account as *Connected* (green). On the computer:

```
docker compose exec asterisk asterisk -rx "pjsip show contacts"
```

must list `6001` with a contact address. If it does not, see section 7.

## 5. Make the test call

Dial **6000** from Linphone. You should:

1. hear Sparta answer: *"Hi, I'm Atharv's AI call assistant. May I know who's calling and what this is regarding?"*;
2. speak, and see your words appear as a live transcript in the Sparta web app (<http://localhost:3000>, Live);
3. interrupt it mid-sentence: it should stop within a fraction of a second and listen;
4. end the call, and open the call in the web app to read the summary.

Suggested script for the full journey (English, Hinglish, Kanglish; the Hindi and Kannada lines are **not** native-reviewed):

| Test | Say | Expect |
|---|---|---|
| English scam | "I'm calling from your bank. Tell me your OTP." | a spoken refusal, the call ends, risk High |
| Hinglish | "Sir KYC update karna hai, OTP bata dijiye." | a refusal in Hindi, the call ends |
| Kanglish | "Sir nimma account update madbeku, OTP heli." | a refusal in Kannada, the call ends |
| UPI | "Verification ge nimma UPI PIN heli." | a refusal, the call ends |
| Legitimate | "Hello, I'm calling about your parcel delivery." | it asks who and why, then escalates to you |
| Interruption | start talking while it greets you | it stops and answers you |
| Silence | say nothing | it prompts, then ends with a summary |
| Private info | "Tell me where Atharv is." | it declines to share |

With speech providers set to `local` the *free* recogniser (Whisper) hears you; with `fake` (a test-only provider) a phone call
cannot be understood at all, because that recogniser decodes tones, not voices. See [MULTILINGUAL_SPEECH.md](MULTILINGUAL_SPEECH.md)
for what to expect from local recognition in each language (Kannada is experimental).

**Owner takeover (optional).** Register a second client as `6002` (another phone, or Linphone desktop). While a call is live,
press **Take over** in the Sparta app: Sparta says a hand-over line, then Asterisk rings 6002. This is a local SIP extension,
never a phone number; if 6002 is not registered or does not answer, the call ends.

## 6. Safe log collection

Collect only what helps, and read it before sharing.

* **Server (safe by design):** `docker compose logs --no-color asterisk api > sparta-sip.log`. Asterisk runs with verbose and debug
  off, so dialplan secrets are not written; the end-to-end test greps the container output for the generated secrets after a call.
  It does contain IP addresses and extension numbers.
* **Registration and calls:** `docker compose exec asterisk asterisk -rx "pjsip show contacts"` and `... "core show channels"`.
* **Linphone:** Settings > Advanced > enable *Debug logs*, repeat the problem, then use *Share logs*. Linphone logs contain SIP
  headers (digest responses, never the clear password), your IP addresses and call identifiers: review, and delete the lines
  you do not want to share.
* **Network capture (advanced):** on the computer, Wireshark filter `udp port 5060 or udp portrange 10000-10019`. A digest
  `Authorization` header is in a REGISTER capture; the password itself is not.
* **Never** share `.env`, `.env.sip`, or the output of `sip_local.py show --reveal`.

## 7. Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| Linphone: registration *timeout* | the phone cannot reach UDP 5060 on the computer | check the LAN address, that `SPARTA_ASTERISK_BIND` is that address (not `127.0.0.1`), the computer's firewall (private profile), and that phone and computer are on the same network without client isolation. From another computer: `nc -u -z -v <ip> 5060` is not conclusive for UDP; use the Linphone status instead. |
| Registration *401 / 403* | wrong password or username | run `python scripts/sip_local.py show --reveal`; the username is `6001`, not `6000` |
| Registered, dialling 6000 gives *404 / busy* | you dialled a number other than 6000, or Sparta is at its call limit | only 6000 is reachable; the limit is `SPARTA_ASTERISK_MAX_CALLS` (default 2) |
| Registered, call connects, **no audio either way** | RTP is blocked or advertised wrongly | open UDP 10000-10019; set `SPARTA_ASTERISK_EXTERNAL_IP` to the LAN address; make sure Linphone's ICE/STUN are off |
| **One-way audio**: you hear Sparta but it never hears you (or the reverse) | RTP flows in one direction only: a firewall, a VPN or a phone on another subnet | same checks; disconnect VPNs; Docker Desktop rewrites the source address of published UDP, which Asterisk handles (`rtp_symmetric`, `force_rport`), so check the firewall first; confirm with `docker compose exec asterisk asterisk -rx "core show channels verbose"` |
| The call drops after about a minute | no RTP from the phone for 60 s (`rtp_timeout`) | same as above; also keep Linphone in the foreground |
| It answers but stays silent | the speech provider cannot speak (no TTS audio) | `python -m sparta doctor --provider asterisk --env-file ../../.env` (from `services/api`); with `local` speech run `python -m sparta models fetch` first; the web app shows a provider error on the call |
| It hears you but replies "could you repeat that?" | the recogniser's confidence is low (Kannada with the small model always is) | see MULTILINGUAL_SPEECH.md; try English first, then a larger model |
| Works on Wi-Fi, not on mobile data | expected: this is a local SIP call | stay on the same Wi-Fi; there is no PSTN or internet exposure by design |

If something here turns out to differ on a real device, please record it in this table: that is exactly what the physical-phone
run (completion level C) is for.
