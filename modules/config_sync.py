import os
import re
import tempfile

import yaml


_KEY = re.compile(r"^(\s*)([A-Za-z0-9_-]+):(.*)$")


def _entries(lines, start, end, indent):
    found = []
    i = start
    while i < end:
        m = _KEY.match(lines[i])
        if not m or lines[i].lstrip().startswith("#") or len(m.group(1)) != indent:
            i += 1
            continue
        j = i + 1
        last = i
        while j < end:
            s = lines[j].strip()
            if s and not s.startswith("#") and (len(lines[j]) - len(lines[j].lstrip())) <= indent:
                break
            if s and not s.startswith("#"):
                last = j
            j += 1
        c = i
        while c > start and lines[c - 1].strip().startswith("#") and (len(lines[c - 1]) - len(lines[c - 1].lstrip())) == indent:
            c -= 1
        found.append((m.group(2), c, i, last + 1, m.group(3).split("#")[0].strip()))
        i = last + 1
    return found


def _load(lines):
    try:
        data = yaml.safe_load("\n".join(lines))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else {}


def _compatible(want, got):
    if got is None or want is None:
        return got is None or want is None or isinstance(want, str)
    if isinstance(want, bool) or isinstance(got, bool):
        return isinstance(want, bool) and isinstance(got, bool)
    if isinstance(want, (int, float)):
        return isinstance(got, (int, float))
    return isinstance(got, type(want))


def _first_edit(user, tpl, u_range, t_range, indent, path, tpl_data, user_data, log):
    u_entries = {e[0]: e for e in _entries(user, *u_range, indent)}
    for key, c, k, end, inline in _entries(tpl, *t_range, indent):
        here = path + [key]
        want = tpl_data
        for p in here:
            want = want.get(p) if isinstance(want, dict) else None
        got = user_data
        for p in path:
            got = got.get(p) if isinstance(got, dict) else None
        got = got.get(key, KeyError) if isinstance(got, dict) else KeyError
        block = tpl[c:end]
        if key not in u_entries:
            at = u_range[1]
            while at > u_range[0] and not user[at - 1].strip():
                at -= 1
            log.append(f"added {'.'.join(here)}")
            return user[:at] + ([""] if indent == 0 else []) + block + user[at:]
        _, uc, uk, uend, _ = u_entries[key]
        if isinstance(want, dict) and want:
            if isinstance(got, dict):
                child_indent = len(tpl[k + 1]) - len(tpl[k + 1].lstrip()) if k + 1 < end else indent + 2
                for ci in range(k + 1, end):
                    if tpl[ci].strip() and not tpl[ci].strip().startswith("#"):
                        child_indent = len(tpl[ci]) - len(tpl[ci].lstrip())
                        break
                edit = _first_edit(user, tpl, (uk + 1, uend), (k + 1, end), child_indent, here, tpl_data, user_data, log)
                if edit is not None:
                    return edit
                continue
            log.append(f"reset {'.'.join(here)}")
            return user[:uk] + tpl[k:end] + user[uend:]
        if not _compatible(want, got):
            log.append(f"reset {'.'.join(here)}")
            return user[:uk] + tpl[k:end] + user[uend:]
    return None


_RETIRED = (("host_update", "auto_reboot"),)


def _remove_retired(user, log):
    for section, key in _RETIRED:
        for name, _c, k, end, _inline in _entries(user, 0, len(user), 0):
            if name != section:
                continue
            child = next((len(line) - len(line.lstrip()) for line in user[k + 1:end]
                          if line.strip() and not line.strip().startswith("#")), 2)
            for cname, cc, _ck, cend, _ in _entries(user, k + 1, end, child):
                if cname == key:
                    log.append(f"removed {section}.{key}")
                    return user[:cc] + user[cend:]
    return None


def sync_config(conf_path, template_path):
    conf_path, template_path = str(conf_path), str(template_path)
    with open(conf_path, "r", encoding="utf-8") as f:
        text = f.read()
    with open(template_path, "r", encoding="utf-8") as f:
        tpl_text = f.read()
    tpl = tpl_text.splitlines()
    tpl_data = _load(tpl)
    user = text.splitlines()
    if tpl_data is None or _load(user) is None:
        return []
    log = []
    while True:
        removed = _remove_retired(user, log)
        if removed is None:
            break
        user = removed
    for _ in range(500):
        edit = _first_edit(user, tpl, (0, len(user)), (0, len(tpl)), 0, [], tpl_data, _load(user), log)
        if edit is None:
            break
        user = edit
        if _load(user) is None:
            return []
    if not log:
        return []
    out = "\n".join(user) + "\n"
    if _load(out.splitlines()) is None:
        return []
    directory = os.path.dirname(os.path.abspath(conf_path))
    with open(conf_path + ".bak", "w", encoding="utf-8", newline="") as f:
        f.write(text)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, prefix=".tuxd-win.conf.", delete=False, newline="") as tmp:
        tmp.write(out)
        temp_path = tmp.name
    os.replace(temp_path, conf_path)
    return log
