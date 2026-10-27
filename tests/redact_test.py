#!/usr/bin/env python3
"""agent-history-tether: the masker.  What looks like a key, a token or a
password is masked whole wherever aht copies text out of a history, and
ordinary code and prose are left as they are.

  [1] leaks: every kind of key at its usual length and twice it, where keys
      stand; names that say a value is a secret (.env, export, YAML, JSON);
      connection strings; passwords with symbols; tokens with text after
      them; passwords of 12 to 16 characters, keys in hex, tokens that start
      with a slash; long tokens, also across the cut of a text over a
      megabyte; private keys however they are wrapped; and the shapes a
      name=value misses (camelCase names, quoted values, flags, cookies,
      Authorization, XML, more kinds of token, keys in base64, Go's
      addresses), each as text and as a history's raw line, ordinary lines
      of the same shapes beside them.  No 12 characters of a key in a row
      are left, the right kind is named, and masking the masked text again
      changes nothing.
  [2] false positives: ordinary lines come out of redact() unchanged, and a
      raw scan of a history line that holds one finds nothing.
  [3] the histories: `aht secrets` lists a private key once, as its whole
      block, and --redact takes the whole block out; a name on any line of
      a tool's output (.env, YAML, JSON inside JSON) is listed once and
      taken out; a guide or code that names BEGIN and END goes through
      `secrets --redact --apply` unchanged.  Every line is still valid JSON
      and a new scan finds nothing.
  [4] with AHT_BEFORE=<the aht.py of an earlier version>: this repository
      and Python's standard library, scanned by both, differ only where a
      rule says why (counts by kind, before and after);
  [5] …and masking takes at most 1.5 times as long as it did: 20 KB of
      prose, a 50 MB history.

Every key, token and password here is made up at run time, in pieces, so
this file holds none.  Nothing outside a throwaway folder is touched.
"""
import base64, contextlib, importlib.util, io, json, os, random, re, shutil, string, sys
import sysconfig, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

FAILS = []
def ck(cond, msg):
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)

# a sandbox: HOME, AHT_HOME and every agent's store are throwaway folders,
# and stand-ins come first on PATH for anything that could start a watcher
sb = Path(tempfile.mkdtemp(prefix="aht_redact_"))
fakebin = sb / "fakebin"
fakebin.mkdir()
for _t in ("launchctl", "systemctl", "schtasks", "osascript", "open"):
    (fakebin / _t).write_text("#!/bin/sh\nexit 0\n")
    (fakebin / _t).chmod(0o755)
os.environ.update(HOME=str(sb / "home"), AHT_HOME=str(sb / ".aht"),
                  PATH=str(fakebin) + os.pathsep + os.environ.get("PATH", ""),
                  AHT_NO_ICONS="1", AHT_NO_NOTIFY="1", AHT_NO_BACKUP="1",
                  AHT_NO_CHECKPOINT="1", AHT_NO_SEARCH_INDEX="1")
(sb / "home").mkdir()
sys.path.insert(0, str(ROOT))
import aht as core                                      # noqa: E402
for _b in core.BACKENDS:
    _d = sb / "tools" / _b.name
    _d.mkdir(parents=True, exist_ok=True)
    os.environ[_b._env_key()] = str(_d)
assert shutil.which("launchctl") == str(fakebin / "launchctl")

R = random.Random(1026)
AN = string.ascii_letters + string.digits
def rk(n, al=AN):
    return "".join(R.choice(al) for _ in range(n))
def kept_runs(text, secret):
    """The runs of 12 characters of `secret` that are still in `text`."""
    return sorted({p[i:i + 12] for p in re.split(r"\s+", secret) for i in range(len(p) - 11)
                   if p[i:i + 12] in text})
GENERIC = ("password or token", "password in a web address")
PK = "PRIV" + "ATE KEY"
def pem_body(lines):
    return [rk(64, AN + "+/") for _ in range(lines)] + [rk(20, AN + "+/") + "=="]
def pem(kind="RSA ", lines=25, headers=()):
    body = pem_body(lines)
    return ("\n".join([f"-----BEGIN {kind}{PK}-----", *headers, *([""] if headers else []),
                       *body, f"-----END {kind}{PK}-----"]), "\n".join(body))
def numbered(text, sep="\t"):
    """As Claude's Read tool shows a file."""
    return "\n".join(f"{i:>6}{sep}{ln}" for i, ln in enumerate(text.split("\n"), 1))
def jwt(payload):
    return ("ey" + "JhbGciOiJSUzI1NiIsImtpZCI6IjEifQ.ey" + "J"
            + rk(payload, AN + "_-") + "." + rk(342, AN + "_-"))

def raw(text):
    """`text` as a history's line holds it: JSON, its quotes and line breaks
    escaped (what `aht secrets` and --redact read)."""
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}})

bad = []
def leak(where, text, secret, kinds, both=False):
    """Mask `text`; nothing of `secret` may be left, and one of `kinds` named.
    Masking it again changes nothing (callers mask text that is masked).
    `both`: the same for the history's raw line that holds `text`."""
    out = core.redact(text)
    left = kept_runs(out, secret)
    if left or not any(f"[{k}: " in out for k in kinds):
        bad.append(f"{where}: {left[:2]} in {out[:160]!r}")
    elif core.redact(out) != out:
        bad.append(f"{where}: masked again, it changes: {core.redact(out)[:160]!r}")
    if both:
        leak(where + ", raw", raw(text), json.dumps(secret)[1:-1], kinds)

PATS = core._secret_patterns()
def untouched(lines):
    """The lines redact() changes, or a raw scan of their history line lists."""
    return [(ln, core.redact(ln)) for ln in lines if core.redact(ln) != ln
            or list(core._scan_bytes(raw(ln).encode(), PATS))]

print("\n[1] leaks: nothing of a key is left, and its kind is named")

# every kind of key, at its usual length and twice it, where keys stand
def keys(x):
    pw = rk(24 * x, AN + "!~")
    putty_body = [rk(64, AN + "+/") for _ in range(4 * x)] + [rk(24, AN + "+/")]
    putty = "\n".join(["PuTTY-User-" + "Key-File-3: ssh-ed25519", "Encryption: none",
                       "Comment: made-up", "Public-Lines: 2", rk(64, AN + "+/"),
                       rk(20, AN + "+/"), f"Private-Lines: {len(putty_body)}", *putty_body,
                       "Private-MAC: " + rk(64, "0123456789abcdef")])
    return [("Anthropic API key", "sk-" + "ant-" + "api03-" + rk(93 * x, AN + "_-") + "AA"),
            ("OpenAI API key", "sk-" + "proj-" + rk(156 * x, AN + "_-")),
            ("Groq API key", "gs" + "k_" + rk(52 * x)),
            ("GitHub token", "gh" + "p_" + rk(36 * x)),
            ("GitHub token", "github_" + "pat_" + rk(22 * x) + "_" + rk(59 * x)),
            ("AWS access key", "AK" + "IA" + rk(16 * x, string.ascii_uppercase + string.digits)),
            ("Google API key", "AI" + "za" + rk(35 * x, AN + "_-")),
            ("Google OAuth token", "ya" + "29." + rk(150 * x, AN + "_-")),
            ("Slack token", "xo" + "xb-" + rk(12, string.digits) + "-"
             + rk(13, string.digits) + "-" + rk(24 * x)),
            ("Stripe key", "sk_" + "live_" + rk(99 * x)),
            ("Hugging Face token", "hf" + "_" + rk(34 * x)),
            ("npm token", "npm" + "_" + rk(36 * x)),
            ("Tailscale key", "tsk" + "ey-auth-" + rk(12 * x) + "CNTRL-" + rk(33 * x)),
            ("JSON web token", jwt(200 * x)),
            ("password or token", rk(40 * x)),
            ("private key", pem(lines=25 * x)[0]),
            ("private key", putty),
            ("password in a web address", f"postgres://deploy:{pw}@db.corp.lan:5432/app")]
PLACES = [("alone", "use {} for the deploy"),
          ("after x-api-key", "curl -H 'x-api-key: {}' https://api.example.com/v1"),
          ("after api_key=", "api_key={}"),
          ("after api_key=, more after it", "api_key={}&v2 was set"),
          ("after a bearer", 'curl -H "Authorization: Bearer {}" https://api.example.com'),
          ("inside JSON", None),
          ("in a web address", "https://api.example.com/v1/items?api_key={}&page=2"),
          ("in a web address's path", "https://hooks.example.com/services/{}/run")]
for x in (1, 2):
    for kind, key in keys(x):
        secret = key.split(":", 2)[2].split("@")[0] if kind == "password in a web address" \
            else "\n".join(key.split("\n")[1:]) if kind == "private key" else key
        for where, form in PLACES:
            if where.startswith("in a web address") and kind in GENERIC + ("private key",):
                continue                    # not something a web address holds
            if kind == "password or token" and where in ("alone", "in a web address's path"):
                continue                    # nothing there says a random word is a key
            text = form.format(key) if form else json.dumps({"env": {"API_KEY": key}})
            leak(f"{kind}, {x}x, {where}", text, secret,
                 [kind] if kind not in GENERIC else GENERIC)
ck(not bad, f"every kind of key, at its usual length and twice it, where keys stand "
            f"({len(bad)}: {bad[:3]})")

# names that say a value is a secret, as .env files, shells, YAML and JSON
# write them; the keyword with more of a name around it
bad = []
NAMES = ["DB_PASSWORD", "POSTGRES_PASSWORD", "MYSQL_ROOT_PASSWORD", "AWS_SECRET_ACCESS_KEY",
         "aws_secret_access_key", "SECRET_KEY", "DJANGO_SECRET_KEY", "JWT_SECRET",
         "client_secret", "client-secret", "clientSecret", "STRIPE_WEBHOOK_SECRET",
         "OPENROUTER_API_KEY", "MISTRAL_API_KEY", "apiKey", "api-key", "GITHUB_TOKEN",
         "NPM_TOKEN", "access_token", "refresh_token", "auth_token", "X-Auth-Token",
         "DB_PASS", "SMTP_PASSWD", "db.password", "spring.datasource.password",
         "private_key", "accessKey", "AUTH", "credentials", "app.secret.value"]
FORMS = [(".env", "{n}={v}"), ("export", "export {n}={v}"), ("export, quoted", 'export {n}="{v}"'),
         ("YAML", "  {n}: {v}"), ("YAML, quoted", "{n}: '{v}'"), ("JSON", None),
         ("compose", "      - {n}={v}"), ("a header", "{n}: {v}"), ("PHP", "'{n}' => '{v}',"),
         ("Go", '{n} := "{v}"')]
for name in NAMES:
    for where, form in FORMS:
        v = rk(R.choice((24, 32, 40, 48)))
        text = form.format(n=name, v=v) if form else json.dumps({name: v})
        leak(f"{name} as {where}", text, v, GENERIC)
basic = base64.b64encode(("deploy:" + rk(20)).encode()).decode()
leak("Authorization: Basic", f"curl -H 'Authorization: Basic {basic}' https://api.example.com",
     basic, GENERIC)
ck(not bad, f"names around the keyword: {len(NAMES)} names in {len(FORMS)} forms, and "
            f"Authorization: Basic ({len(bad)}: {bad[:3]})")

# connection strings: any host, an empty user, a percent-encoded password
bad = []
pw = rk(20)
enc = rk(4) + "%40" + rk(4) + "%2F" + rk(6)
for url in ["postgres://app:{}@localhost:5432/app", "postgres://app:{}@192.0.2.10:5432/app",
            "mongodb://root:{}@mongo:27017/admin", "redis://:{}@cache:6379/0",
            "postgresql://app:{}@[::1]:5432/app", "mysql://app:{}@db.corp.lan/app",
            "amqp://guest:{}@rabbit", "DATABASE_URL=postgres://app:{}@db:5432/app?sslmode=require"]:
    for p in (pw, enc):
        leak(url, url.format(p), p, GENERIC)
        if not bad and "@" in core.redact(url.format(p)):
            out = core.redact(url.format(p))
            if not (out.split("://")[0] in url and "@" in out
                    and out.split("@")[1] == url.format(p).split("@")[1]):
                bad.append(f"{url}: the rest of the address is not readable: {out!r}")
ck(not bad, f"connection strings: any host form, an empty user, a percent-encoded password; "
            f"the rest of the address stays readable ({len(bad)}: {bad[:3]})")

# passwords with symbols in them, and tokens with text right after them
bad = []
def sym(shape):
    """A password of this shape: each `a` a random letter or digit."""
    return "".join(rk(1) if c == "a" else c for c in shape)
for shape in ["aaa$aaa!aaa#aaaa", "a%40aaaaa-aaaaaa", "aaa(aaa)aaaaaaaa", "aaa{aaa}aaaaaaaa",
              "a#aa$aa!aaa^aaa", "aa4%aaa&aaa*aaa!", "aaaaaaaa$", "aa(aaaa9aaaa9aaa",
              "aa9)aaaa!aaaa9aa", "aa9]aaaa}aaaa9aa"]:
    p = sym(shape)
    for form in ["password={}", 'export DB_PASS="{}"', '{{"password": "{}"}}',
                 "postgres://app:{}@db.corp.lan:5432/app"]:
        leak(f"{shape} in {form}", form.format(p), p, GENERIC)
for n in (24, 64, 70, 80, 120):
    t = rk(n)
    for form in ["password={}...", "password={}…", "api_key={}</code>", "secret: {}%0A",
                 "<code>api_key={}</code>", "access_token={}$", "token={}{{", "token={}("]:
        leak(f"{n} characters, {form}", form.format(t), t, GENERIC)
ck(not bad, f"passwords with symbols, and tokens with ..., </code> or %0A after them "
            f"({len(bad)}: {bad[:3]})")

# passwords of 12 to 16 characters (too few for their entropy to say they
# are random), keys in hex, random tokens that start with a slash
bad = []
HEX = "0123456789abcdef"
for n in range(12, 17):
    for _ in range(20):
        p = ""
        while len(set(p)) < 7:
            p = list(rk(n - 3) + R.choice(string.ascii_lowercase)
                     + R.choice(string.ascii_uppercase) + R.choice(string.digits))
            R.shuffle(p)
            p = "".join(p)
        for form in ["password={}", 'export DB_PASS="{}"', "PGPASSWORD={} psql -h db -U app",
                     '{{"password": "{}"}}']:
            leak(f"{n} characters, {form}", form.format(p), p, GENERIC)
for n in (24, 32, 40, 64):
    h = rk(n, HEX)
    for form in ["secret={}", '"api_key": "{}"', "export WEBHOOK_SECRET={}"]:
        leak(f"{n} hex digits, {form}", form.format(h), h, GENERIC)
for n in (44, 64):
    for _ in range(3):
        t = "/" + rk(n - 1, AN + "+/")
        for form in ["secret={}", "token: {}"]:
            leak(f"a token of {n} that starts with a slash, {form}", form.format(t), t, GENERIC)
ck(not bad, f"passwords of 12 to 16 characters, keys in hex, tokens that start with a slash "
            f"({len(bad)}: {bad[:3]})")

# tokens far longer than the stretch searched around a needle
bad = []
for n in (900, 1500, 5000):
    t = jwt(n)
    for where, form in [("alone", "{}"), ("id_token in JSON", '{{"id_token": "{}"}}'),
                        ("a cookie", "Cookie: session={}; path=/"), ("id_token:", 'id_token: "{}"')]:
        leak(f"a JSON web token with a {n}-character payload, {where}", form.format(t), t,
             ["JSON web token"])
    t2 = t.rsplit(".", 1)[0]
    leak(f"an unsigned JSON web token, {n}", f"token {t2}", t2, ["JSON web token"])
for kind, key in keys(40):
    if kind in ("password in a web address", "private key", "Slack token"):
        continue
    leak(f"{kind}, 40 times as long", f"api_key={key}", key, [kind] + list(GENERIC))
ck(not bad, f"tokens of any length: a JSON web token with a payload of 900, 1500 and 5000 "
            f"characters, every kind 40 times as long ({len(bad)}: {bad[:3]})")

# a text over a megabyte is cut a little past where its caller cuts it before
# it is masked: a key that starts before the caller's cut and runs on past
# that is masked whole as far as the caller keeps it
bad = []
filler = "The build ran and the tests passed; nothing else changed here. " * 20000
for what, key, secret, kinds in [
        ("a JSON web token, a 6000-character payload", jwt(6000), None, ["JSON web token"]),
        ("a private key of 120 lines", *pem(lines=120), ["private key"]),
        ("a token of 9000 after api_key=", *(lambda t: ("api_key=" + t, t))(rk(9000)), GENERIC)]:
    secret = secret or key
    for n, cut in [(4000, lambda t: core._redact_head(t, 4000)[:4000]),
                   (400, lambda t: core._masked(t, 400)), (200, lambda t: core._masked(t, 200))]:
        text = filler[:n - 100] + "\n" + key + " " + filler
        out = cut(text)
        left = kept_runs(out, secret)
        if len(text) <= 1 << 20 or left or not any(f"[{k}: " in out for k in kinds):
            bad.append(f"{what}, cut at {n}: {left[:2]} in {out[-160:]!r}")
ck(not bad, f"a key across the cut of a text over a megabyte ({len(bad)}: {bad[:3]})")

# private keys, however they are wrapped
bad = []
plain, body = pem()
enc_pem, enc_body = pem(headers=("Proc-Type: 4,ENCRYPTED", "DEK-Info: AES-128-CBC,"
                                 + rk(32, "0123456789ABCDEF")))
pgp_body = [rk(64, AN + "+/") for _ in range(20)] + [rk(30, AN + "+/"), "=" + rk(4)]
pgp = "\n".join(["-----BEGIN PGP " + PK + " BLOCK-----", "Version: GnuPG v2", "",
                 *pgp_body, "-----END PGP " + PK + " BLOCK-----"])
ssh, ssh_body = pem("OPENSSH ")
cut = plain.split("\n-----END")[0]
WRAPS = [("plain", plain, body), ("an OpenSSH key", ssh, ssh_body),
         ("JSON", json.dumps({"private_key": plain}), body),
         ("JSON inside JSON", json.dumps(json.dumps({"private_key": plain})), body),
         ("three times escaped", json.dumps(json.dumps(json.dumps({"k": plain}))), body),
         ("a Read tool's output", numbered(plain), body),
         ("a Read tool's output, arrows", numbered(plain, "→"), body),
         ("a Read tool's output in JSON", json.dumps(numbered(plain)), body),
         ("an encrypted key", enc_pem, enc_body), ("a PGP block", pgp, "\n".join(pgp_body[:-1])),
         ("its leading dashes stripped", plain.lstrip("-"), body),
         ("cut off before its END", cut + "\n[output truncated]", body),
         ("cut off, a Read tool's output", numbered(cut), body),
         ("cut off, in JSON", json.dumps({"out": cut})[:-2], body),
         ("in a sentence", f"The agent asks: is {plain} the key to use?", body)]
for where, text, secret in WRAPS:
    leak(f"a private key, {where}", text, secret, ["private key"])
out = core.redact(plain + "\nThe key above is new.")
ck(not bad and out.endswith("]\nThe key above is new.") and "BEGIN RSA" in out,
   f"private keys: {len(WRAPS)} wrappings, masked whole, the header shown, the words after "
   f"it kept ({len(bad)}: {bad[:3]})")

# what a name=value misses, as text and as a history's raw line; ordinary
# lines of the same shapes (`fps`) stay as they are
bad, fps = [], []
v = rk(32)
UPD = string.ascii_uppercase + string.digits
# a name on a line after the first, as a tool shows a file
for t in [f"DEBUG=1\nSECRET_KEY={v}\n", f"X=1\nAPI_KEY={v}", numbered(f"DEBUG=1\nDB_PASSWORD={v}"),
          f"db:\n  password: {v}\n",
          json.dumps({"Name": "prod/db", "SecretString": json.dumps({"username": "a", "password": v})})]:
    leak(f"a name on line 2 of {t[:20]!r}", t, v, GENERIC, both=True)
# camelCase names, and the names apps and frameworks give their keys
for nm in ["SecretAccessKey", "SessionToken", "accessToken", "refreshToken", "idToken", "dbPassword",
           "AccountKey", "SharedAccessKey", "webhookSecret", "encryptionKey", "secretKey",
           "MasterUserPassword", "passphrase", "BORG_PASSPHRASE", "APP_KEY", "RAILS_MASTER_KEY",
           "AZURE_DEVOPS_PAT", "ENCRYPTION_KEY", "SIGNING_KEY", "HMAC_KEY", "JWT_KEY"]:
    for form in ('{{"{n}": "{v}"}}', '  {n}: "{v}",', "{n}={v}"):
        leak(f"{nm} as {form}", form.format(n=nm, v=v), v, GENERIC, both=True)
acct = rk(86, AN + "+/") + "=="
leak("an Azure connection string", "DefaultEndpointsProtocol=https;AccountName=a;AccountKey="
     f"{acct};EndpointSuffix=core.windows.net", acct, GENERIC, both=True)
fps += ["tokenCount: 3", "passwordHash = hash(pw)", 'accessTokenUrl: "https://example.com/token"',
        "getAccessToken()", "isTokenExpired", "refreshToken: refreshToken", 'sort_key="created_at"',
        "apiKey: process.env.API_KEY", "primary_key=True", "exports.isEofToken = isEofToken;"]
# a value in quotes runs to its closing quote, over , ; ' ( ) & and quotes
for s, forms in [(sym("aaaa,aaaa;aaaa(aaaa)aaaa&aa=aaaa"),
                  ("SECRET_KEY = '{}'", 'password: "{}"', None)),
                 ("django-insecure-" + sym("a!a9(&a=a2#aa8&aa4=aa)a6+aa0$a*aa1@aa5^aa"),
                  ("SECRET_KEY = '{}'", None)),
                 (sym("aaaa'aaaa,aaaa;aaaa)aaa"), ('DB_PASSWORD="{}"', None)),
                 (sym('aaaa"aaaa,aaaa;aaaa)aaa'), ("password: '{}'", None))]:
    for form in forms:
        text = json.dumps({"password": s}) if form is None else form.format(s)
        leak(f"in quotes: {form}", text, s, GENERIC, both=True)
fps += ["password = getpass.getpass(prompt='Password: ')", 'token = "Bearer " + tok',
        '"token_scopes": "repo,read:org,workflow"', '"token_note": "CI deploy for staging",',
        'o.params.push("access_token="+(i||N.ACCESS_TOKEN||""))',
        'u&&"?api_key="===u[0].slice(-9),tiles:["https://x/{z}.png?api_key="],size:256},'
        'layers:[{id:"terrain"}]']
# shapes that read as names, paths or words, and are not: a base32 seed, a
# value of capitals and digits, dotted random parts, one that starts with a
# dot, words a generator joined after a password's name, digits in letters
pw_words = ["copper", "plaza", "cosmic", "orbit", "tundra", "maple", "quartz", "ember"]
phrase = "-".join(R.choice(pw_words) for _ in range(4))
for t, s in [("TOTP_SECRET={}", R.choice(string.ascii_uppercase) + rk(31, string.ascii_uppercase
                                                                     + "234567")),
             ("DB_PASSWORD={}", R.choice(string.ascii_uppercase) + rk(19, UPD)),
             ("SECRET_KEY={}", rk(6, string.ascii_letters) + "." + rk(20)),
             ("DB_PASSWORD='{}'", "." + rk(19, AN + "^-@#*")),
             ("DB_PASSWORD={}", phrase), ("password: {}", phrase.title() + "7"),
             ("API_KEY={}", rk(3, string.ascii_uppercase) + rk(2, string.digits)
              + rk(1, string.ascii_lowercase) + rk(1, string.digits) + rk(1, string.ascii_uppercase)
              + rk(10, string.ascii_lowercase))]:
    leak(t.format("…"), t.format(s), s, GENERIC, both=True)
fps += ["DB_PASSWORD_FILE=/run/secrets/db", "password: ./secrets/db", "secret: my-app-secrets",
        "MAX_RETRIES=5", "token: MAX_RETRIES", "password: DEFAULT_PASSWORD", "auth: HMACSHA256",
        "secret_key: SECRETKEYBASE", "secret = spring.datasource.password", "password: .env"]
# no name=value: Authorization with any scheme, flags, cookies, XML
for t in ["Authorization: Token {v}", '{{"Authorization": "ApiKey {v}"}}',
          "Authorization: SSWS {v}", "mysql -u root -p{v} app", "mysql -u root --password {v}",
          "docker login -u bot -p {v} ghcr.io", "sshpass -p {v} ssh host",
          "twine upload -u __token__ -p {v} dist/*", "redis-cli -a {v} ping",
          "gh auth login --with-token {v}", "tool --token '{v}'",
          "curl -u admin" ":{v} https://api.example.com/", "> Cookie: theme=dark; session={v}",
          "< Set-Cookie: sessionid={v}; Path=/; HttpOnly", "<password>{v}</password>",
          '<add key="ClearTextPassword" value="{v}" />', "auth: {{ user: 'bot', pass: '{v}' }}"]:
    leak(t[:40], t.format(v=v), v, GENERIC, both=True)
fps += ["--password-file /run/secrets/db", "docker login -u bot --password-stdin",
        "docker run -p 8080:80 nginx", "Cookie: theme=dark", "Authorization: see the README",
        "mysql -u root -p app", "curl -u $USER:$PASS https://example.com",
        "the Authorization header is required", "<password>${DB_PASSWORD}</password>"]
# more kinds of token, alone and in a web address
for kind, tok in [("GitLab token", "gl" + "pat-" + rk(20, AN + "_-")),
                  ("GitLab token", "gl" + "rt-" + rk(24, AN + "_-")),
                  ("SendGrid key", "S" + "G." + rk(22, AN + "_-") + "." + rk(43, AN + "_-")),
                  ("PyPI token", "pypi-" + "AgEI" + rk(150, AN + "_-")),
                  ("age key", "AGE-SEC" + "RET-KEY-1" + rk(58, "QPZRY9X8GF2TVDW0S3JN54KHCE6MUA7L")),
                  ("Vault token", "hv" + "s." + rk(90, AN + "_-")),
                  ("DigitalOcean token", "dop" + "_v1_" + rk(64, HEX)),
                  ("Shopify token", "shp" + "at_" + rk(32, HEX)),
                  ("Docker Hub token", "dckr" + "_pat_" + rk(27, AN + "_-")),
                  ("Atlassian token", "ATA" + "TT3" + rk(180, AN + "_-="))]:
    leak(f"{kind}, alone", f"my token is {tok}, use it", tok, [kind], both=True)
    leak(f"{kind}, in a web address", f"git push https://oauth2:{tok}@git.example.com/x.git",
         tok, [kind], both=True)
hook = rk(24)
leak("a Slack webhook", "curl -X POST https://hooks.sl" + "ack.com/services/T"
     f"{rk(8, UPD)}/B{rk(8, UPD)}/{hook} -d x", hook, ["Slack webhook"], both=True)
bot = rk(35, AN + "_-")
leak("a Telegram bot's address", "curl https://api.tele" + "gram.org/bot"
     f"{rk(10, string.digits)}:{bot}/getUpdates", bot, ["Telegram bot token"], both=True)
# a private key in base64 (kubeconfig, a Kubernetes secret, base64 at 76)
b = base64.b64encode(pem()[0].encode()).decode()
cert = base64.b64encode(("-----BEGIN CERTIFICATE-----\n" + rk(64) + "\n").encode()).decode()
leak("a key in base64, kubeconfig", f"users:\n- name: a\n  user:\n    client-key-data: {b}\n",
     b, ["private key"], both=True)
leak("a key in base64, tls.key", f"data:\n  tls.crt: {cert}\n  tls.key: {b}\n", b[20:],
     ["private key"], both=True)
wrapped = "\n".join(b[i:i + 76] for i in range(0, len(b), 76))
leak("a key in base64, wrapped", f"$ base64 key.pem\n{wrapped}\n$ ", wrapped, ["private key"],
     both=True)
fps += [f"tls.crt: {cert}"]
# Go's address, a password with an @ in it
pw = rk(20, AN + "!#")
leak("Go's address", f"DSN=root:{pw}@tcp(127.0.0.1:3306)/app?parseTime=true", pw, GENERIC,
     both=True)
at_pw = rk(3) + "@" + pw
leak("an @ in the password", f"postgres://app:{at_pw}@db:5432/app", at_pw, GENERIC, both=True)
fps += ["ssh://git@github.com:22/owner/repo.git", "git@github.com:owner/repo.git", "user@host:/path"]
# still masked: a random file name under a name, a weak password with digits
cfg = f"config/{rk(32)}.json"
leak("a random file name", f"GOOGLE_APPLICATION_CREDENTIALS={cfg}", cfg, GENERIC, both=True)
weak = [w for w in ("Summer" + "2024!", "Welcome" + "123!")
        if w in core.redact(f"password={w}") or w in core.redact(f"DB_PASSWORD: {w}")]
changed = untouched(fps)
ck(not bad and not weak and not changed,
   f"what a name=value misses, as text and as a raw history line: names on later lines, "
   f"camelCase, quotes, generated shapes, flags, cookies, XML, 11 more kinds of token, keys in "
   f"base64, Go's addresses ({len(bad)}: {bad[:3]}; weak passwords left: {weak}); "
   f"{len(fps)} ordinary lines of those shapes unchanged ({changed[:3]})")

print("\n[2] false positives: ordinary lines are left as they are")
sha = "".join(R.choice("0123456789abcdef") for _ in range(40))
digest = "".join(R.choice("0123456789abcdef") for _ in range(64))
uid = "%s-%s-4%s-a%s-%s" % (rk(8, "0123456789abcdef"), rk(4, "0123456789abcdef"),
                            rk(3, "0123456789abcdef"), rk(3, "0123456789abcdef"),
                            rk(12, "0123456789abcdef"))
png = base64.b64encode(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\x00\x00\x00\x01\x00"
                       b"\x08\x06\x00\x00\x00\x5c\x72\xa8\x66\x00\x00\x00\x04gAMA").decode()
ORDINARY = [
    "token = tokenizer.encode(text)",
    "max_tokens=4096",
    "tokens_used: 1234",
    "password_hash = bcrypt.hash(pw)",
    'api_key=os.environ["OPENAI_API_KEY"]',
    "password: ${DB_PASSWORD}",
    'secret_name="prod/db"',
    "TOKEN_URL=https://oauth2.googleapis.com/token",
    'token_type: "Bearer"',
    "auth: true",
    '"password": "<redacted>"',
    "DB_PASSWORD=changeme",
    'secret_key_base: <%= ENV["SECRET_KEY_BASE"] %>',
    "access_key_id = None",
    "credentials_file=~/.aws/credentials",
    f"git checkout {sha}",
    f"session {uid} resumed",
    f"sha256: {digest}",
    f'<img src="data:image/png;base64,{png}">',
    "https://www.google.com/search?q=python+tokenizer&oq=python+tokenizer&sourceid=chrome&ie=UTF-8",
    'password = getpass.getpass("Password: ")',
    "secret = secrets.token_hex(32)",
    "token = jwt.encode(payload, key, algorithm=\"HS256\")",
    "if not token: raise ValueError('no token')",
    "def check_password(password: str) -> bool:",
    "    return hmac.compare_digest(password_hash, hashed(password))",
    "const token = await getAccessToken(scopes);",
    "const secret = process.env.JWT_SECRET;",
    "let password = req.body.password;",
    "headers: { Authorization: `Bearer ${token}` },",
    'password := os.Getenv("DB_PASSWORD")',
    "token, err := auth.GetToken(ctx)",
    "secretKey := []byte(cfg.Secret)",
    'let token = env::var("API_TOKEN")?;',
    "let secret_key = SecretKey::from_slice(&bytes)?;",
    "fn verify(password: &str, hash: &PasswordHash) -> bool {",
    "The password must be 12 characters or longer.",
    "Reset your token from the settings page if it leaks.",
    "We pass the secret through an environment variable, never on the command line.",
    "Auth is handled by the gateway; the token lives for an hour.",
    "The tokenizer splits text into tokens before the model sees it.",
    "bypass_cache=true",
    "secretary: Jane",
    "compass_heading = 270",
    "token_count = len(tokens)",
    "password_min_length: 12",
    "TOKEN_ENDPOINT=https://login.example.com/oauth2/v2.0/token",
    "token_expires: 3600",
    "secret_ttl = 86400",
    "PASSWORD_FIELD = 'password'",
    "auth_header = 'Authorization'",
    "API_KEY_HEADER=X-Api-Key",
    "password_regex = r'^(?=.*[A-Z]).{12,}$'",
    "api_key_prefix: sk-",
    "token_budget: 200000",
    "--password-file /run/secrets/db",
    "password: $(cat /run/secrets/db)",
    "password=%(password)s",
    "token: {{ secrets.GITHUB_TOKEN }}",
    "AUTH_SECRET=${AUTH_SECRET:-}",
    "pass: true",
    "set password=%DB_PASSWORD%",
    "postgres://postgres:" + "postgres@localhost:5432/postgres",
    "postgresql://user:" + "password@hostname:5432/dbname",
    "redis://localhost:6379/0",
    "https://example.com:8443/path?x=1",
    "ssh://git@github.com:22/owner/repo.git",
    "auth = HTTPBasicAuth(user, password)",
    "basic authentication is not enough here",
    "credentials = service_account.Credentials.from_service_account_file(path)",
    "client_secret = config.get('oauth', 'client_secret')",
    "self.access_token = access_token",
    "token=self._next_token()",
    "Bearer tokens expire after an hour.",
    "token = 'abc'",
    "password = None",
    "-----BEGIN PUBLIC KEY-----",
    "eyJ is how a base64 JSON object starts.",
    "client.login(username=user, password=pw).wait()",
    "x = foo(token=tok).bar()",
    "Pass: the build passed on the second try.",
    "Auth: see the README for how the token flow works.",
    "Secret: none of this is stored on the server.",
    f"SSH_AUTH_SOCK=/private/tmp/com.apple.launchd.{rk(10)}/Listeners",
    f"SSH_AUTH_SOCK=/tmp/ssh-{rk(12)}/agent.{R.randint(1000, 99999)}",
    "GOOGLE_APPLICATION_CREDENTIALS=/home/dev/keys/sa-2024.json",
    "ssl_private_key: /etc/ssl/private/example.com.key",
    "token: /var/run/secrets/kubernetes.io/serviceaccount/token",
    "auth_callback: /auth/callback?next=/dashboard",
    'log.info(f"token_wait={elapsed_ms_t1 - elapsed_ms_t0:.1f} ms")',
]
changed = untouched(ORDINARY)
ck(len(ORDINARY) >= 60 and not changed,
   f"{len(ORDINARY)} ordinary lines come out of redact() unchanged, and a raw scan lists "
   f"none ({len(changed)}: {changed[:4]})")

# a guide and code that name a key's BEGIN and END line, with no key between
GUIDE = (f"Your deploy key file starts with `-----BEGIN OPENSSH {PK}-----`.\n\n"
         "1. Open Settings, Deploy keys, Add key.\n"
         "2. Paste the whole file, from that first line down to the last one.\n"
         "3. Tick Allow write access only for the release job.\n\n"
         f"The last line is `-----END OPENSSH {PK}-----`. Nothing after it.")
CHECK = (f"def load(text):\n    if not text.startswith('-----BEGIN {PK}-----'):\n"
         "        raise ValueError('not a key')\n"
         "    body = ''.join(text.strip().splitlines()[1:-1])\n"
         "    der = base64.b64decode(body)\n"
         f"    assert text.rstrip().endswith('-----END {PK}-----')\n    return der\n")
# what the masker read as a key before, each kind once or more: a name
# after :: (pytest, Rust, PHP, C++), a test runner's PASS line, letters of
# other languages and a tokenizer's pieces, a service's address or an
# image's tag, a secret manager's reference or a placeholder, a relative
# path, an address, an ARN, a fingerprint or a hash, code
FIXED = [
    GUIDE, CHECK,
    "pytest tests/test_auth.py::TestLogin::test_password_reset -x",
    "python -m pytest tests/unit/test_token.py::test_refresh_expired_token_returns_401",
    "FAILED tests/test_password.py::test_hash_roundtrip - AssertionError",
    "cargo test auth::tests::login_with_expired_token",
    "use crate::auth::{Claims, Token};",
    "auth::middleware::verify_token(&req)",
    "if (Auth::attempt($credentials)) {",
    "Auth::login($user, $remember);",
    "Password::sendResetLink($request->only('email'));",
    "return at::_ops::_make_dep_token::call(c10::optTypeMetaToScalarType(options.dtype_opt()));",
    "--- PASS: TestCache/evicts_oldest_entry (0.00s)",
    "    --- PASS: TestSplit/simple (0.00s)",
    "PASS: gcc.dg/pr12345.c",
    "PASS: tests/unit/tokenizer.sh",
    "pass: TestRateLimiter/refills_after_window",
    '"Unexpected_token_1012": "予期しないトークンです。",',
    '"password_required": "パスワードを入力してください",',
    '"token_expired": "トークンの有効期限が切れました",',
    '"auth_title": "Přihlášení",',
    'password_reset_subject: "Zurücksetzen Ihres Passworts"',
    '{"id": 4512, "token": "ĠInternational", "logprob": -0.12}',
    '"token": "▁International", "logprob": -0.003',
    "AUTH_SERVICE_URL=http://auth-service:8080/api/v1",
    "curl http://auth:4000/oauth/token",
    "GET http://token-service:9000/v1/introspect 200 12ms",
    "image: auth-" "service:1.4.2-alpine3.18",      # in two: a secret scanner reads it as a key
    "image: ghcr.io/acme/token-exchange:v0.3.1-beta.2",
    "docker build -t auth-api:1.2.3-dev .",
    "DB_PASSWORD=op://Engineering/Postgres/password",
    "OPENAI_API_KEY=op://Private/OpenAI/credential",
    "STRIPE_SECRET_KEY=op://prod/stripe/secret-key",
    "DB_PASSWORD=ref+awsssm://prod/db/password",
    "token: sm://projects/my-proj/secrets/api-token",
    "password: vault:kv/prod/db#password",
    "password: %{DB_PASSWORD}",
    "password: \"#{ENV.fetch('DB_PASSWORD')}\"",
    "password: $env:DB_PASSWORD",
    "password = $__file{/run/secrets/db_password}",
    'token = "${match[2]}"',
    "secret: ${args[0]}",
    "TOKEN=${BASH_REMATCH[1]}",
    "GOOGLE_APPLICATION_CREDENTIALS=config/service-account.json",
    "credentials: secrets/gcp-service-account.json",
    "auth_config: config/auth/providers.yaml",
    "token_cache: data/cache/oauth-tokens.db",
    "secret_version: projects/123456789/secrets/db-password/versions/3",
    "AUTH_ISSUER=https://login.microsoftonline.com/common/v2.0",
    "token_issuer: https://accounts.google.com",
    "auth_redirect: https://app.acme-corp.io/auth/callback",
    "auth_domain: my-app-12345.firebaseapp.com",
    '"secret_arn": "arn:aws:secretsmanager:us-east-1:123456789012:secret:prod/db-AbCdEf",',
    f"auth_key_fingerprint: SHA256:{rk(43, AN + '+/')}",
    f"token_sha256: {digest}",
    f"secret_checksum: {sha}",
    "auth_method: oauth2-client-credentials",
    "const token = this.tokenMap!.find(node => node.type === 'x')",
    "return token = scanTemplateAndSetTokenValue(!isTaggedTemplate)",
    "const auth = useAuth()!.currentUser",
    "let token = this.scanner.next()!.value",
    "const token = (jsTokens as any).default",
    "token_number = self.tokens_taken+len(self.tokens)",
    "'password' => Hash::make($request->password),",
    ".special-token:not(:empty):before { content: \"x\"; }",
    ".secret-banner:focus-within{outline:2px solid}",
    '        Token.Prompt: "ansibrightblue",',
    "s3gen_tokens, s3gen_token_lens = self._s3tokenizer(s3gen_mel)",
    "this.nextToken=null}fetch(){return this.input}",
    "SERVER_AUTH: _ASN1Object",
    'LS32_PAT = "(?:{hex}:{hex}|{ipv4})"',
]
changed = untouched(FIXED)
ck(not changed, f"{len(FIXED)} lines the masker read as keys before come out unchanged, and a "
                f"raw scan lists none; the guide and the code that name BEGIN and END among "
                f"them ({len(changed)}: {changed[:3]})")

print("\n[3] the histories: a private key found once, whole, and taken out whole")
def transcript(proj, name, entries):
    store = Path(os.environ["AHT_ROOT_CLAUDE"]) / core._key_claude(proj)
    store.mkdir(parents=True, exist_ok=True)
    f = store / f"{name}.jsonl"
    f.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return f
def tool(proj, sid, name, inp, shown, result=None):
    """A tool call and its output, as Claude Code writes them."""
    tid = "toolu_" + rk(20)
    call = {"type": "assistant", "cwd": proj, "sessionId": sid, "message": {
        "role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": name,
                                          "input": inp}]}}
    out = {"type": "user", "cwd": proj, "sessionId": sid, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": shown}]}}
    if result is not None:
        out["toolUseResult"] = result
    return [call, out]
ppk = next(k for kind, k in keys(1) if k.startswith("PuTTY"))
CASES = []
for where, text, body_lines in [
        ("cat of a key", plain, body), ("an encrypted key", enc_pem, enc_body),
        ("a PGP block", pgp, "\n".join(pgp_body[:-1])), ("an OpenSSH key", ssh, ssh_body)]:
    CASES.append((where, lambda p, s, t=text: tool(p, s, "Bash", {"command": "cat k"}, t,
                                                    {"stdout": t, "stderr": ""}), body_lines))
CASES += [
    ("Read of a key, tabs", lambda p, s: tool(p, s, "Read", {"file_path": p + "/id_rsa"},
                                              numbered(plain), {"type": "text", "file": {
                                                  "filePath": p + "/id_rsa", "content": plain}}),
     body),
    ("Read of a key, arrows", lambda p, s: tool(p, s, "Read", {"file_path": p + "/id_rsa"},
                                                numbered(plain, "→")), body),
    ("a service account file", lambda p, s: tool(
        p, s, "Bash", {"command": "cat sa.json"},
        json.dumps({"type": "service_account", "private_key": plain}, indent=2),
        {"stdout": json.dumps({"type": "service_account", "private_key": plain}, indent=2)}),
     body),
    ("Read of a service account file", lambda p, s: tool(
        p, s, "Read", {"file_path": p + "/sa.json"},
        numbered(json.dumps({"type": "service_account", "private_key": plain}, indent=2))),
     body),
    ("cut off", lambda p, s: tool(p, s, "Bash", {"command": "head -c 900 k"}, cut[:900]),
     "\n".join(l for l in body.split("\n") if l in cut[:900])),
    ("a PuTTY key", lambda p, s: tool(p, s, "Bash", {"command": "cat k.ppk"}, ppk),
     "\n".join(l for l in ppk.split("\n")[4:-1] if ":" not in l)),
]
pbad = []
for i, (where, make, secret) in enumerate(CASES):
    proj = os.path.realpath(str(sb / "home" / f"proj{i}"))
    os.makedirs(proj)
    f = transcript(proj, f"s{i}", make(proj, f"s{i}"))
    finds = core.scan_secrets(proj)
    pks = [x for x in finds if x["kind"] == "private key"]
    if len(pks) != 1 or len(finds) != 1:
        pbad.append(f"{where}: {len(finds)} finds, {[x['masked'] for x in finds]}")
        continue
    if not pks[0]["masked"].startswith(("BEGIN", "PuTTY")):
        pbad.append(f"{where}: shown as {pks[0]['masked']!r}")
    res = core.redact_in_histories(pks[0]["fingerprint"], proj, apply=True)
    after = f.read_text()
    try:
        valid = all(json.loads(l) for l in after.splitlines())
    except ValueError:
        valid = False
    left = kept_runs(after, secret)
    again = core.scan_secrets(proj)
    if not res.get("applied") or left or not valid or again:
        pbad.append(f"{where}: applied {res.get('applied')}, {len(left)} runs left, JSON "
                    f"valid {valid}, found again {[x['masked'] for x in again]}")
ck(not pbad, f"aht secrets: one find per key, its header shown; --redact takes out the "
             f"whole block in {len(CASES)} cases, every line is valid JSON, a new scan finds "
             f"nothing ({pbad[:3]})")

# the same in a long history: a key 1 MB in, and one at its very end
proj = os.path.realpath(str(sb / "home" / "long"))
os.makedirs(proj)
filler = [{"type": "user", "cwd": proj, "message": {"role": "user", "content": rk(1000)}}
          for _ in range(1000)]
f = transcript(proj, "long", filler + tool(proj, "long", "Bash", {"command": "cat k"}, plain)
               + filler + tool(proj, "long", "Bash", {"command": "cat k2"}, ssh))
finds = core.scan_secrets(proj)
for x in finds:
    core.redact_in_histories(x["fingerprint"], proj, apply=True)
after = f.read_text()
ck(len(finds) == 2 and not kept_runs(after, body) and not kept_runs(after, ssh_body)
   and all(json.loads(l) for l in after.splitlines()) and not core.scan_secrets(proj),
   f"a long history: two keys, both taken out whole ({[x['masked'] for x in finds]})")

# a name on a later line of a tool's output: after an escaped line break
# or a Read tool's line number, in YAML, in JSON inside JSON
v = rk(32)
env = f"DEBUG=1\nSECRET_KEY={v}\n"
RAW = [("cat .env", lambda p, s: tool(p, s, "Bash", {"command": "cat .env"}, env,
                                      {"stdout": env, "stderr": ""})),
       ("Read of .env", lambda p, s: tool(p, s, "Read", {"file_path": p + "/.env"},
                                          numbered(f"DEBUG=1\nDB_PASSWORD={v}"))),
       ("YAML, line 2", lambda p, s: tool(p, s, "Bash", {"command": "cat values.yaml"},
                                          f"db:\n  password: {v}\n")),
       ("a secretsmanager SecretString", lambda p, s: tool(
           p, s, "Bash", {"command": "aws secretsmanager get-secret-value --secret-id db"},
           json.dumps({"Name": "db", "SecretString": json.dumps({"user": "a", "password": v})},
                      indent=4)))]
rbad = []
for i, (where, make) in enumerate(RAW):
    proj = os.path.realpath(str(sb / "home" / f"raw{i}"))
    os.makedirs(proj)
    f = transcript(proj, f"r{i}", make(proj, f"r{i}"))
    finds = core.scan_secrets(proj)
    if len(finds) != 1:
        rbad.append(f"{where}: {len(finds)} finds, {[x['masked'] for x in finds]}")
        continue
    res = core.redact_in_histories(finds[0]["fingerprint"], proj, apply=True)
    after = f.read_text()
    try:
        valid = all(json.loads(l) for l in after.splitlines())
    except ValueError:
        valid = False
    if not res.get("applied") or kept_runs(after, v) or not valid or core.scan_secrets(proj):
        rbad.append(f"{where}: applied {res.get('applied')}, {kept_runs(after, v)[:1]} left, "
                    f"JSON valid {valid}")
ck(not rbad, f"a name on a later line of a tool's output, in {len(RAW)} forms: listed once, "
             f"taken out, every line valid JSON, a new scan finds nothing ({rbad[:3]})")

# a guide and code that name BEGIN and END, beside a key: `aht secrets`
# lists the key alone, and `secrets --redact --apply` takes it out and
# leaves the guide and the code as they were
proj = os.path.realpath(str(sb / "home" / "guide"))
os.makedirs(proj)
reply = {"type": "assistant", "cwd": proj, "sessionId": "g", "message": {
    "role": "assistant", "content": [{"type": "text", "text": GUIDE}]}}
f = transcript(proj, "g", [reply] + tool(proj, "g", "Write", {"file_path": proj + "/load.py",
                                                               "content": CHECK}, "written")
               + tool(proj, "g", "Bash", {"command": "cat k"}, plain, {"stdout": plain}))
finds = core.scan_secrets(proj)
rc, said = None, io.StringIO()
if len(finds) == 1:
    with contextlib.redirect_stdout(said):
        rc = core.main(["secrets", proj, "--redact", finds[0]["fingerprint"], "--apply"])
after = [json.loads(l) for l in f.read_text().splitlines()]
ck(len(finds) == 1 and rc == 0 and "removed from" in said.getvalue()
   and after[0]["message"]["content"][0]["text"] == GUIDE
   and after[1]["message"]["content"][0]["input"]["content"] == CHECK
   and not kept_runs(f.read_text(), body) and not core.scan_secrets(proj),
   f"a guide and code that name BEGIN and END: only the key beside them is listed "
   f"({[x['masked'] for x in finds]}); secrets --redact --apply takes it out and leaves "
   f"them as they were")

before_path = os.environ.get("AHT_BEFORE")
if before_path:
    print(f"\n[4] this repository and Python's standard library, before and after")
    # a copy of the earlier version, imported under a name of its own
    bdir = sb / "before"
    bdir.mkdir()
    shutil.copy(before_path, bdir / "aht_before.py")
    spec = importlib.util.spec_from_file_location("aht_before", str(bdir / "aht_before.py"))
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)

    def finds_of(mod, data):
        return list(mod._scan_bytes(data, mod._secret_patterns()))
    def creds64(v):
        try:
            return ":" in base64.b64decode(v, validate=True).decode()
        except Exception:
            return False
    SECRET_NAME = re.compile(r"(?i)(?:pass(?:word|wd|phrase)?|pwd|secret|token|auth|credentials?"
                             r"|pat|(?:api|access|private|app|master|encryption|signing|hmac|jwt"
                             r"|account|shared|secret)[_-]?key)[\w.-]*\\*[\"']?\s*(?:=>|:=|[:=])"
                             r"\s*\\*[\"']?$")
    # why this round masks what the earlier version did not
    WHY = [("a private key, masked whole now",
            lambda k, v, c: k == "private key"),
           ("a known kind of token", lambda k, v, c: k not in GENERIC),
           ("a password in a web address to any host",
            lambda k, v, c: k == "password in a web address" and ("://" in c or "@tcp(" in v)),
           ("Authorization: Basic, a user and a password in base64",
            lambda k, v, c: creds64(v) and re.search(r"(?i)basic\s*$", c)),
           ("a generated value after a name that says it is a secret",
            lambda k, v, c: k == "password or token" and SECRET_NAME.search(c)
            and not core._code(v) and core._entropy(v) >= 3),
           ("a value on a command line, in a cookie or after Authorization",
            lambda k, v, c: k == "password or token" and re.search(
                r"(?i)(?:\s-[pau]\s*|--[\w-]+\s+|cookie:.*=|authorization\W+(?:\w+\s+)?)$", c))]
    # …and why it no longer masks what the earlier version did
    WHY_NOT = [("code: a call or an index after a name",
                lambda k, v, c: re.search(r"[(\[]", v) and core._code(v.rstrip("([") or v)),
               ("code: a type or a class's name", lambda k, v, c: core._code(v)),
               ("a private key's header with no key under it",
                lambda k, v, c: k == "private key" and not core._material(v)),
               ("a placeholder, a name, a path, a reference or words",
                lambda k, v, c: core._PLACEHOLDER.search(v) or core._shaped(v) or core._path(v)
                or core._text(v)),
               ("a name with :: after it (pytest, Rust, PHP, C++)",
                lambda k, v, c: v.startswith(":")),
               ("letters of a language other than English",
                lambda k, v, c: any(ord(ch) > 127 and ch.isalpha() for ch in v)),
               ("code after a quote that closed a string (\"token=\"+t)",
                lambda k, v, c: v[:1] in "+="),
               ("a name whose last part says it holds something else (token_lens)",
                lambda k, v, c: re.search(r"(?i)[_.-](?:lens|num|number|idx|digest|checksum"
                                          r"|fingerprint|arn|md5|sha\d*)\W*$", c))]
    files = sorted(p for ext in ("*.py", "*.js", "*.md") for p in ROOT.rglob(ext)
                   if not {".git", "node_modules"} & set(p.parts))
    nrepo = len(files)
    stdlib = Path(sysconfig.get_paths()["stdlib"])
    files += sorted(p for p in stdlib.rglob("*.py") if "site-packages" not in p.parts)
    counts = {"before": {}, "after": {}}
    new, lost = [], []
    for p in files:
        try:
            data = p.read_bytes()
        except OSError:
            continue
        fb, fa = finds_of(old, data), finds_of(core, data)
        for name, fs in (("before", fb), ("after", fa)):
            for k, *_ in fs:
                counts[name][k] = counts[name].get(k, 0) + 1
        for k, a, b, v in fa:
            if not any(a < b2 and a2 < b for _k, a2, b2, _v in fb):
                new.append((p, k, v, data[max(0, a - 80):a].decode("utf-8", "replace")))
        for k, a, b, v in fb:
            if not any(a < b2 and a2 < b for _k, a2, b2, _v in fa):
                lost.append((p, k, v, data[max(0, a - 80):a].decode("utf-8", "replace")))
    print(f"   {nrepo} files of this repository, {len(files) - nrepo} of the standard library "
          f"({stdlib.name}); finds by kind, before -> after:")
    for k in sorted(set(counts["before"]) | set(counts["after"])):
        print(f"     {k:<28} {counts['before'].get(k, 0):>5} -> {counts['after'].get(k, 0)}")
    unexplained = []
    for p, k, v, ctx in new:
        why = next((w for w, rule in WHY if rule(k, v, ctx)), None)
        print(f"     new: {p.name}: {k} [{v[:24]}…]: {why or 'NO REASON'}")
        if why is None:
            unexplained.append(f"{p.name}: {k}: {ctx[-40:]!r}")
    for p, k, v, ctx in lost:
        why = next((w for w, rule in WHY_NOT if rule(k, v, ctx)), None)
        print(f"     no longer: {p.name}: {k} [{v[:24]}…]: {why or 'NO REASON'}")
        if why is None:
            unexplained.append(f"{p.name}: no longer {k}: {v[:30]!r}")
    ck(not unexplained, f"nothing is masked, or no longer masked, without a reason: {len(new)} "
                        f"new, {len(lost)} no longer ({unexplained[:4]})")

    print("\n[5] the time it takes, before and after")
    def best(fn, n):
        t = []
        for _ in range(n):
            t0 = time.perf_counter()
            fn()
            t.append(time.perf_counter() - t0)
        return min(t)
    # 20 KB of prose that talks about passwords, tokens and keys
    W = ("the a to of and in that is for it with as on was we be this have are not but at "
         "from or by one all would there their what so up out if about who get which go me "
         "when make can like time no just him know take people into year your good some "
         "could them see other than then now look only come its over think also back after "
         "use two how our work first well way even new want because any these give day most "
         "password token secret key auth pass bearer basic login session cookie access "
         "private client credentials api header value config deploy rotate leak").split()
    prose = ""
    while len(prose) < 20000:
        sent = [R.choice(W) for _ in range(R.randint(6, 18))]
        if R.random() < 0.2:
            sent.insert(R.randint(0, len(sent)), R.choice(["password:", "token=", "api_key:",
                                                           "Bearer", "secret ="]))
        prose += " ".join(sent).capitalize() + ". "
    tb = best(lambda: old.redact(prose), 15)
    ta = best(lambda: core.redact(prose), 15)
    ck(ta <= 1.5 * tb, f"20 KB of prose: {ta * 1000:.1f} ms, {tb * 1000:.1f} ms before "
                     f"({ta / tb:.2f}x)")

    # a 50 MB history: what an agent's transcript holds — messages, code from
    # the standard library, tool calls with their usage counts, an image now
    # and then — and a key in every hundredth line
    code = [p.read_text("utf-8", "replace") for p in sorted(stdlib.glob("*.py"))[:200]]
    code = [c[i:i + 3000] for c in code for i in range(0, len(c), 3000)]
    keyed = [k for _kind, k in keys(1)]
    lines, size, n = [], 0, 0
    while size < 50 << 20:
        n += 1
        r = R.random()
        if n % 100 == 0:
            e = {"type": "user", "message": {"role": "user", "content": R.choice(
                ["use {}", "api_key={}", "export GITHUB_TOKEN={}", "Authorization: Bearer {}",
                 "postgres://app:{}@localhost/app"]).format(R.choice(keyed))}}
        elif r < 0.3:
            e = {"type": "user", "message": {"role": "user", "content": prose[
                R.randrange(0, 15000):][:R.randint(80, 2000)]}}
        elif r < 0.65:
            e = {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": prose[R.randrange(0, 15000):][:R.randint(80, 600)]},
                {"type": "tool_use", "id": "toolu_" + rk(20), "name": "Edit", "input": {
                    "file_path": "/w/app.py", "old_string": R.choice(code)[:800],
                    "new_string": R.choice(code)[:800]}}],
                "usage": {"input_tokens": R.randint(1, 9), "cache_creation_input_tokens":
                          R.randint(0, 9999), "cache_read_input_tokens": R.randint(0, 99999),
                          "output_tokens": R.randint(1, 999), "service_tier": "standard"}}}
        elif r < 0.98:
            e = {"type": "user", "toolUseResult": {"stdout": "", "stderr": ""}, "message": {
                "role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_x",
                                             "content": R.choice(code)}]}}
        else:
            e = {"type": "user", "message": {"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                             "data": base64.b64encode(R.randbytes(30000)).decode()}}]}}
        line = json.dumps(e) + "\n"
        lines.append(line)
        size += len(line)
    hist = "".join(lines).encode()
    del lines
    pb, pa = old._secret_patterns(), core._secret_patterns()
    fb = len(list(old._scan_bytes(hist, pb)))
    fa = len(list(core._scan_bytes(hist, pa)))
    tb = best(lambda: list(old._scan_bytes(hist, pb)), 3)
    ta = best(lambda: list(core._scan_bytes(hist, pa)), 3)
    ck(ta <= 1.5 * tb, f"a {len(hist) >> 20} MB history: {ta:.2f} s, {tb:.2f} s before "
                     f"({ta / tb:.2f}x; {fa} finds, {fb} before)")

shutil.rmtree(sb, ignore_errors=True)
print()
if FAILS:
    print(f"❌ {len(FAILS)} FAILED")
    sys.exit(1)
print("✅ ALL REDACT TESTS PASSED")
