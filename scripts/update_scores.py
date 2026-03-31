#!/usr/bin/env python3
"""
DST IPL Auto-Updater
====================
Fetches IPL match scorecards from ESPN Cricinfo and updates data.json
on GitHub — preserving all previous match data untouched.

How it works:
1. Reads current data.json from your GitHub repo
2. Detects the next un-done match (lowest id where done=false)
3. Fetches that match's scorecard from ESPN Cricinfo
4. Maps player stats to your 88-player squad
5. Marks the match done=true
6. Pushes the updated data.json back to GitHub via the API

Run: python scripts/update_scores.py [--match-id N] [--espn-id XXXXX] [--dry-run]
"""

import json, re, sys, os, time, base64, argparse
import urllib.request, urllib.error
from datetime import datetime

# ─── CONFIG ────────────────────────────────────────────────────────────────────
GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO   = os.environ.get("GITHUB_REPO",  "aashishsingh-png/ipl2026-fantasy-groupb")
DATA_FILE     = "data.json"

# ESPN Cricinfo match IDs for IPL 2026 — fill these in as the season progresses
# Find them in the URL: espncricinfo.com/series/ipl-2026-XXXXXX/TEAM-vs-TEAM-Nth-match-YYYYYY/
ESPN_MATCH_IDS = {
    0: 1527674,   # Match 1: RCB vs SRH  (done)
    1: 1527675,   # Match 2: MI vs KKR   (done)
    2: 1527676,   # Match 3: RR vs CSK   (done)
    3: 1527677,   # Match 4: PBKS vs GT  ← add when known
    4: 1527678,   # Match 5             ← add when known
    # Add more as season progresses...
}

# ─── SQUAD MAP — exact player names matching data.json keys ───────────────────
ALL_SQUAD_PLAYERS = [
    "Mohammed Siraj","Quinton de Kock","Marco Jansen","Varun Chakaravarthy",
    "Kuldeep Yadav","Sunil Narine","Hardik Pandya","Finn Allen","Prasidh Krishna",
    "Priyansh Arya","Vaibhav Arora","Bhuvneshwar Kumar","Ishan Kishan","Rohit Sharma",
    "Jofra Archer","Jasprit Bumrah","Shivam Dube","Ajinkya Rahane","Axar Patel",
    "Jacob Bethell","Will Jacks","Ashwani Kumar","Shubman Gill","Abhishek Sharma",
    "Yashasvi Jaiswal","Mohammed Shami","Avesh Khan","Nitish Kumar Reddy",
    "Angkrish Raghuvanshi","Harshal Patel","Pathum Nissanka","Azmatullah Omarzai",
    "T Natarajan","Rinku Singh","KL Rahul","Aiden Markram","Rishabh Pant",
    "Ruturaj Gaikwad","Dewald Brevis","Tim David","Dhruv Jurel","Prabhsimran Singh",
    "Jason Holder","Harsh Dubey","Riyan Parag","Ravindra Jadeja","Sai Sudharsan",
    "Virat Kohli","Josh Hazlewood","Suryakumar Yadav","Marcus Stoinis","Mukesh Kumar",
    "Digvesh Singh Rathi","Karun Nair","Khaleel Ahmed","Heinrich Klaasen",
    "Rajat Patidar","Sanju Samson","Cameron Green","Kagiso Rabada","Tristan Stubbs",
    "Krunal Pandya","Ryan Rickelton","Ayush Mhatre","Romario Shepherd",
    "Washington Sundar","Mitchell Marsh","Nicholas Pooran","Shreyas Iyer",
    "Philip Salt","Yuzvendra Chahal","Ravi Bishnoi","Noor Ahmad","Matt Henry",
    "Abishek Porel","Devdutt Padikkal","Shashank Singh","Vaibhav Sooryavanshi",
    "Tilak Varma","Arshdeep Singh","Rashid Khan","Jos Buttler","Shimron Hetmyer",
    "Travis Head","Jitesh Sharma","Trent Boult","Mitchell Santner","Nehal Wadhera",
]

# Name aliases: ESPN name → your data.json name
NAME_ALIASES = {
    "Virat Kohli": "Virat Kohli",
    "V Kohli": "Virat Kohli",
    "RG Sharma": "Rohit Sharma",
    "Rohit Sharma": "Rohit Sharma",
    "JJ Bumrah": "Jasprit Bumrah",
    "Jasprit Bumrah": "Jasprit Bumrah",
    "TA Boult": "Trent Boult",
    "Trent Boult": "Trent Boult",
    "HH Pandya": "Hardik Pandya",
    "Hardik Pandya": "Hardik Pandya",
    "SA Yadav": "Suryakumar Yadav",
    "Suryakumar Yadav": "Suryakumar Yadav",
    "NT Tilak Varma": "Tilak Varma",
    "Tilak Varma": "Tilak Varma",
    "RD Rickelton": "Ryan Rickelton",
    "Ryan Rickelton": "Ryan Rickelton",
    "FH Allen": "Finn Allen",
    "Finn Allen": "Finn Allen",
    "AM Rahane": "Ajinkya Rahane",
    "Ajinkya Rahane": "Ajinkya Rahane",
    "C Green": "Cameron Green",
    "Cameron Green": "Cameron Green",
    "A Raghuvanshi": "Angkrish Raghuvanshi",
    "Angkrish Raghuvanshi": "Angkrish Raghuvanshi",
    "RK Singh": "Rinku Singh",
    "Rinku Singh": "Rinku Singh",
    "CV Varun": "Varun Chakaravarthy",
    "Varun Chakaravarthy": "Varun Chakaravarthy",
    "SP Narine": "Sunil Narine",
    "Sunil Narine": "Sunil Narine",
    "VG Arora": "Vaibhav Arora",
    "Vaibhav Arora": "Vaibhav Arora",
    "B Kumar": "Bhuvneshwar Kumar",
    "Bhuvneshwar Kumar": "Bhuvneshwar Kumar",
    "Ishan Kishan": "Ishan Kishan",
    "JA Duffy": None,  # Not in squad
    "R Shepherd": "Romario Shepherd",
    "Romario Shepherd": "Romario Shepherd",
    "KH Pandya": "Krunal Pandya",
    "Krunal Pandya": "Krunal Pandya",
    "PD Salt": "Philip Salt",
    "Philip Salt": "Philip Salt",
    "D Padikkal": "Devdutt Padikkal",
    "Devdutt Padikkal": "Devdutt Padikkal",
    "RM Patidar": "Rajat Patidar",
    "Rajat Patidar": "Rajat Patidar",
    "JM Sharma": "Jitesh Sharma",
    "Jitesh Sharma": "Jitesh Sharma",
    "TH David": "Tim David",
    "Tim David": "Tim David",
    "TM Head": "Travis Head",
    "Travis Head": "Travis Head",
    "Abhishek Sharma": "Abhishek Sharma",
    "K Nitish Kumar Reddy": "Nitish Kumar Reddy",
    "Nitish Kumar Reddy": "Nitish Kumar Reddy",
    "H Klaasen": "Heinrich Klaasen",
    "Heinrich Klaasen": "Heinrich Klaasen",
    "HS Dubey": "Harsh Dubey",
    "Harsh Dubey": "Harsh Dubey",
    "HV Patel": "Harshal Patel",
    "Harshal Patel": "Harshal Patel",
    "J Archer": "Jofra Archer",
    "Jofra Archer": "Jofra Archer",
    "V Sooryavanshi": "Vaibhav Sooryavanshi",
    "Vaibhav Sooryavanshi": "Vaibhav Sooryavanshi",
    "YBK Jaiswal": "Yashasvi Jaiswal",
    "Yashasvi Jaiswal": "Yashasvi Jaiswal",
    "R Jadeja": "Ravindra Jadeja",
    "Ravindra Jadeja": "Ravindra Jadeja",
    "R Bishnoi": "Ravi Bishnoi",
    "Ravi Bishnoi": "Ravi Bishnoi",
    "MJ Henry": "Matt Henry",
    "Matt Henry": "Matt Henry",
    "R Parag": "Riyan Parag",
    "Riyan Parag": "Riyan Parag",
    "D Jurel": "Dhruv Jurel",
    "Dhruv Jurel": "Dhruv Jurel",
    "Sanju Samson": "Sanju Samson",
    "Ruturaj Gaikwad": "Ruturaj Gaikwad",
    "Shivam Dube": "Shivam Dube",
    "A Mhatre": "Ayush Mhatre",
    "Ayush Mhatre": "Ayush Mhatre",
    "RG Sharma": "Rohit Sharma",
}

# ─── HELPERS ───────────────────────────────────────────────────────────────────

def resolve_player(espn_name):
    """Map ESPN name to squad name. Returns None if not in squad."""
    # Direct lookup
    if espn_name in NAME_ALIASES:
        return NAME_ALIASES[espn_name]
    # Fuzzy: try last name match
    last = espn_name.split()[-1].lower()
    for squad_name in ALL_SQUAD_PLAYERS:
        if squad_name.lower().endswith(last):
            return squad_name
    # Fuzzy: try any word match
    words = [w.lower() for w in espn_name.split() if len(w) > 3]
    for squad_name in ALL_SQUAD_PLAYERS:
        swords = squad_name.lower().split()
        if any(w in swords for w in words):
            return squad_name
    return None

def empty_entry(lineup=True, impact=False):
    return {
        "runs": 0, "balls": 0, "fours": 0, "sixes": 0, "duck": False,
        "wickets": 0, "blbw": 0, "dots": 0, "maidens": 0,
        "overs": 0, "runs_conceded": 0,
        "catches": 0, "stumpings": 0, "rod": 0, "roi": 0,
        "lineup": lineup, "impact": impact
    }

def fetch_url(url, retries=3):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            if i == retries - 1:
                raise
            print(f"  Retry {i+1} after error: {e}")
            time.sleep(2)

# ─── ESPN SCORECARD PARSER ──────────────────────────────────────────────────────

def fetch_espn_scorecard(espn_match_id):
    """
    Fetch full scorecard from ESPN Cricinfo.
    Returns dict: { player_name: { batting: {...}, bowling: {...}, fielding: {...} } }
    """
    url = f"https://www.espncricinfo.com/matches/engine/match/{espn_match_id}.json"
    print(f"  Fetching ESPN JSON: {url}")

    try:
        raw = fetch_url(url)
        match_data = json.loads(raw)
    except Exception as e:
        print(f"  ESPN JSON endpoint failed ({e}), trying scorecard page...")
        return fetch_espn_scorecard_html(espn_match_id)

    return parse_espn_json(match_data)


def parse_espn_json(match_data):
    """Parse ESPN's match JSON into per-player stats."""
    players = {}

    innings_list = match_data.get("innings", [])
    for inning in innings_list:
        # BATTING
        for bat in inning.get("batsmen", []):
            name = bat.get("longName", bat.get("name", ""))
            squad_name = resolve_player(name)
            if not squad_name:
                continue
            if squad_name not in players:
                players[squad_name] = empty_entry()
            p = players[squad_name]

            runs = int(bat.get("runs", 0))
            balls = int(bat.get("balls", 0))
            fours = int(bat.get("fours", 0))
            sixes = int(bat.get("sixes", 0))
            dismissal = bat.get("dismissalText", {}).get("long", "").lower()
            duck = (runs == 0 and balls > 0 and "not out" not in dismissal and dismissal != "")

            p["runs"] = runs
            p["balls"] = balls
            p["fours"] = fours
            p["sixes"] = sixes
            p["duck"] = duck
            p["lineup"] = True

        # BOWLING
        for bowl in inning.get("bowlers", []):
            name = bowl.get("longName", bowl.get("name", ""))
            squad_name = resolve_player(name)
            if not squad_name:
                continue
            if squad_name not in players:
                players[squad_name] = empty_entry()
            p = players[squad_name]

            overs_str = str(bowl.get("overs", "0"))
            try:
                overs = float(overs_str)
                full = int(overs)
                frac = round(overs - full, 1)
                overs_decimal = full + frac
            except:
                overs_decimal = 0

            p["overs"] = overs_decimal
            p["runs_conceded"] = int(bowl.get("runs", 0))
            p["wickets"] = int(bowl.get("wickets", 0))
            p["dots"] = int(bowl.get("dots", 0))
            p["maidens"] = int(bowl.get("maidens", 0))
            p["lineup"] = True

        # FIELDING — parse from dismissals
        for bat in inning.get("batsmen", []):
            dismissal = bat.get("dismissalText", {}).get("long", "").lower()
            # caught by
            c_match = re.search(r"c ([a-z\s]+?) b ", dismissal)
            if c_match:
                fielder_name = c_match.group(1).strip().title()
                sq = resolve_player(fielder_name)
                if sq:
                    if sq not in players: players[sq] = empty_entry()
                    players[sq]["catches"] = players[sq].get("catches", 0) + 1
            # stumped by
            if "st " in dismissal:
                st_match = re.search(r"st ([a-z\s]+?) b ", dismissal)
                if st_match:
                    fielder_name = st_match.group(1).strip().title()
                    sq = resolve_player(fielder_name)
                    if sq:
                        if sq not in players: players[sq] = empty_entry()
                        players[sq]["stumpings"] = players[sq].get("stumpings", 0) + 1
            # run out
            if "run out" in dismissal:
                ro_match = re.search(r"run out \(([^)]+)\)", dismissal)
                if ro_match:
                    fielder_name = ro_match.group(1).strip().title()
                    sq = resolve_player(fielder_name)
                    if sq:
                        if sq not in players: players[sq] = empty_entry()
                        players[sq]["rod"] = players[sq].get("rod", 0) + 1

            # Detect b/lbw for bowler
            bowler_field = bat.get("dismissalText", {}).get("long", "")
            bowler_match = re.search(r" b ([A-Za-z\s]+)$", bowler_field.strip())
            is_blbw = bowler_field.lower().strip().startswith("b ") or \
                      bowler_field.lower().strip().startswith("lbw b ")
            if is_blbw and bowler_match:
                bowler_name = bowler_match.group(1).strip()
                sq = resolve_player(bowler_name)
                if sq:
                    if sq not in players: players[sq] = empty_entry()
                    players[sq]["blbw"] = players[sq].get("blbw", 0) + 1

    # Detect impact subs
    for event in match_data.get("matchEvents", []):
        desc = event.get("description", "").lower()
        if "impact" in desc and "sub" in desc:
            # Try to parse "X in for Y" pattern
            in_match = re.search(r"([a-z\s]+) in for ([a-z\s]+)", desc)
            if in_match:
                sub_in = in_match.group(1).strip().title()
                sub_out = in_match.group(2).strip().title()
                sq_in = resolve_player(sub_in)
                sq_out = resolve_player(sub_out)
                if sq_in:
                    if sq_in not in players: players[sq_in] = empty_entry()
                    players[sq_in]["impact"] = True
                    players[sq_in]["lineup"] = False
                if sq_out:
                    if sq_out not in players: players[sq_out] = empty_entry()
                    players[sq_out]["lineup"] = True
                    players[sq_out]["impact"] = False

    return players


def fetch_espn_scorecard_html(espn_match_id):
    """Fallback: scrape ESPN HTML scorecard page."""
    url = f"https://www.espncricinfo.com/series/ipl-2026/scorecard/{espn_match_id}"
    print(f"  Fetching ESPN HTML scorecard...")
    try:
        html = fetch_url(url)
        return parse_espn_html(html)
    except Exception as e:
        print(f"  HTML fetch also failed: {e}")
        return {}


def parse_espn_html(html):
    """
    Parse ESPN HTML scorecard. Extracts bowling table rows with dots column.
    Returns same format as parse_espn_json.
    """
    players = {}

    # Extract bowling tables — ESPN HTML has: O M R W Econ 0s 4s 6s WD NB
    # Match bowling rows: name | O | M | R | W | Econ | 0s | ...
    bowl_pattern = re.compile(
        r'<td[^>]*>.*?player.*?</a>.*?</td>'   # player name cell
        r'(?:.*?<td[^>]*>(\d+(?:\.\d+)?)</td>)'  # O
        r'(?:.*?<td[^>]*>(\d+)</td>)'             # M
        r'(?:.*?<td[^>]*>(\d+)</td>)'             # R
        r'(?:.*?<td[^>]*>(\d+)</td>)'             # W
        r'(?:.*?<td[^>]*>[\d.]+</td>)'            # Econ
        r'(?:.*?<td[^>]*>(\d+)</td>)',             # 0s (dots)
        re.DOTALL
    )

    # Simpler: parse the | O | M | R | W | Econ | 0s | table
    # ESPN HTML scorecard has structured divs — extract text blocks
    # Find all "| x | x | x | x |" rows after stripping HTML
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text)

    # Find bowling figures pattern: digits overs, digits M, digits R, digits W, decimal Econ, digits dots
    bowl_rows = re.findall(
        r'([A-Z][a-zA-Z\s\.\'-]{3,30})\s+'
        r'(\d+(?:\.\d)?)\s+'   # overs
        r'(\d+)\s+'            # maidens
        r'(\d+)\s+'            # runs
        r'(\d+)\s+'            # wickets
        r'[\d.]+\s+'           # econ
        r'(\d+)',              # dots
        text
    )

    for row in bowl_rows:
        name_raw, overs, maidens, runs, wickets, dots = row
        name_raw = name_raw.strip()
        sq = resolve_player(name_raw)
        if not sq:
            continue
        if sq not in players:
            players[sq] = empty_entry()
        try:
            players[sq]["overs"] = float(overs)
            players[sq]["maidens"] = int(maidens)
            players[sq]["runs_conceded"] = int(runs)
            players[sq]["wickets"] = int(wickets)
            players[sq]["dots"] = int(dots)
            players[sq]["lineup"] = True
        except:
            pass

    # Parse batting — find R B 4s 6s SR patterns
    bat_rows = re.findall(
        r'([A-Z][a-zA-Z\s\.\'-]{3,30})\s+'
        r'(\d+)\s+'   # runs
        r'(\d+)\s+'   # balls
        r'(\d+)\s+'   # 4s
        r'(\d+)\s+'   # 6s
        r'[\d.]+',    # SR
        text
    )

    for row in bat_rows:
        name_raw, runs, balls, fours, sixes = row
        name_raw = name_raw.strip()
        sq = resolve_player(name_raw)
        if not sq:
            continue
        if sq not in players:
            players[sq] = empty_entry()
        try:
            players[sq]["runs"] = int(runs)
            players[sq]["balls"] = int(balls)
            players[sq]["fours"] = int(fours)
            players[sq]["sixes"] = int(sixes)
            players[sq]["lineup"] = True
        except:
            pass

    return players


# ─── GITHUB API ────────────────────────────────────────────────────────────────

def github_get(path):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "dst-ipl-updater"
    })
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def github_put(path, content_str, sha, commit_msg):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    payload = json.dumps({
        "message": commit_msg,
        "content": base64.b64encode(content_str.encode()).decode(),
        "sha": sha
    }).encode()
    req = urllib.request.Request(url, data=payload, method="PUT", headers={
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "dst-ipl-updater"
    })
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Auto-update IPL match scores")
    parser.add_argument("--match-id", type=int, default=None,
                        help="Force update a specific match id (0-based)")
    parser.add_argument("--espn-id", type=int, default=None,
                        help="Override ESPN match ID")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print result without pushing to GitHub")
    args = parser.parse_args()

    print("=" * 60)
    print("DST IPL Auto-Updater")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # ── 1. Fetch current data.json from GitHub ──────────────────────
    print("\n[1/4] Fetching current data.json from GitHub...")
    try:
        gh_file = github_get(DATA_FILE)
        current_json = json.loads(base64.b64decode(gh_file["content"]))
        file_sha = gh_file["sha"]
        print(f"  ✓ Loaded. Last updated: {current_json.get('lastUpdated','unknown')}")
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        sys.exit(1)

    # ── 2. Find which match to update ──────────────────────────────
    print("\n[2/4] Detecting next match to update...")
    if args.match_id is not None:
        target_mi = args.match_id
        print(f"  → Forced to match {target_mi}")
    else:
        target_mi = None
        for m in current_json["matches"]:
            if not m["done"]:
                target_mi = m["id"]
                break
        if target_mi is None:
            print("  ✓ All matches already marked done. Nothing to update.")
            sys.exit(0)
        print(f"  → Next undone match: {target_mi} ({current_json['matches'][target_mi]['teams']})")

    # ── 3. Fetch scorecard ──────────────────────────────────────────
    print(f"\n[3/4] Fetching scorecard for match {target_mi}...")
    espn_id = args.espn_id or ESPN_MATCH_IDS.get(target_mi)
    if not espn_id:
        print(f"  ✗ No ESPN match ID configured for match {target_mi}.")
        print(f"    Add it to ESPN_MATCH_IDS in this script, or pass --espn-id XXXXX")
        sys.exit(1)

    print(f"  ESPN match ID: {espn_id}")
    try:
        scorecard = fetch_espn_scorecard(espn_id)
        print(f"  ✓ Got stats for {len(scorecard)} players")
    except Exception as e:
        print(f"  ✗ Scorecard fetch failed: {e}")
        sys.exit(1)

    # ── 4. Merge into data.json ─────────────────────────────────────
    print(f"\n[4/4] Merging stats into data.json...")
    mk = f"m{target_mi}"
    updated_count = 0
    skipped = []

    for squad_name in ALL_SQUAD_PLAYERS:
        if squad_name in scorecard:
            stats = scorecard[squad_name]
            current_json["players"][squad_name][mk] = stats
            updated_count += 1
        else:
            # Not in this match — leave as null (preserves previous data untouched)
            skipped.append(squad_name)

    # Safety check: don't mark done if too few players found (match may be live/incomplete)
    MIN_PLAYERS_REQUIRED = 5
    if updated_count < MIN_PLAYERS_REQUIRED:
        print(f"\n  ⚠️  Only {updated_count} players found — match may still be live or ESPN data incomplete.")
        print(f"     NOT marking match as done. Re-run after the match finishes.")
        print(f"     (Requires at least {MIN_PLAYERS_REQUIRED} players to mark done)")
        if not args.dry_run:
            sys.exit(0)  # Exit cleanly without pushing anything

    # Mark match as done
    current_json["matches"][target_mi]["done"] = True
    current_json["lastUpdated"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"  ✓ Updated {updated_count} players")
    print(f"  → {len(skipped)} players not in this match (left as null)")
    if updated_count > 0:
        print(f"\n  Players updated:")
        for name, stats in scorecard.items():
            pts_est = estimate_pts(stats)
            print(f"    {name:<30} ~{pts_est:>3} pts  "
                  f"({stats['runs']}r {stats['balls']}b "
                  f"{stats['wickets']}wkt {stats['overs']}ov "
                  f"{stats['dots']}dots)")

    # ── Push or dry-run ─────────────────────────────────────────────
    new_json_str = json.dumps(current_json, indent=2, ensure_ascii=False)

    if args.dry_run:
        print(f"\n[DRY RUN] Would push {len(new_json_str)} bytes to GitHub.")
        print(f"  Snippet of updated match {target_mi} data:")
        sample = {k: v for k, v in current_json["players"].items()
                  if v[mk] is not None}
        print(f"  {list(sample.keys())[:5]}...")
    else:
        try:
            commit_msg = (f"Auto-update Match {target_mi+1}: "
                          f"{current_json['matches'][target_mi]['teams']} "
                          f"— {updated_count} players")
            github_put(DATA_FILE, new_json_str, file_sha, commit_msg)
            print(f"\n  ✓ Pushed to GitHub: {commit_msg}")
        except Exception as e:
            print(f"\n  ✗ GitHub push failed: {e}")
            # Save locally as fallback
            with open("data_updated.json", "w") as f:
                f.write(new_json_str)
            print(f"  → Saved locally as data_updated.json")
            sys.exit(1)

    print("\n✓ Done!\n")


def estimate_pts(d):
    """Quick estimate for logging."""
    def eco(rc, ov):
        if ov < 2: return 0
        e = rc / ov
        if e < 5: return 6
        if e <= 5.99: return 4
        if e <= 7: return 2
        if e <= 11: return -2
        if e <= 12: return -4
        return -6
    def sr(r, b):
        if b < 10: return 0
        s = (r/b)*100
        if s > 170: return 6
        if s >= 150: return 4
        if s >= 130: return 2
        if s >= 70: return 0
        if s >= 60: return -2
        if s >= 50: return -4
        return -6

    p = d['runs'] + d['fours']*4 + d['sixes']*6
    ms = 16 if d['runs']>=100 else 12 if d['runs']>=75 else 8 if d['runs']>=50 else 4 if d['runs']>=25 else 0
    p += ms
    if d.get('duck'): p -= 2
    p += sr(d['runs'], d['balls'])
    p += d['wickets']*30 + d['blbw']*8 + d['dots'] + d['maidens']*12
    wk = d['wickets']
    wb = 12 if wk>=5 else 8 if wk>=4 else 4 if wk>=3 else 0
    p += wb
    if d['overs'] > 0: p += eco(d['runs_conceded'], d['overs'])
    p += d['catches']*8 + (4 if d['catches']>=3 else 0)
    p += d['stumpings']*12 + d['rod']*12 + d['roi']*6
    if d['lineup']: p += 4
    if d['impact']: p += 4
    return p


if __name__ == "__main__":
    main()
