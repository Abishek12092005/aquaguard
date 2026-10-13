"""Snap a typed word to the real spelling of a known place, then let the
geocoder supply everything about that place.

The geocoders index exact spellings. "chenn" reaches Chennai, but "hennai" -
'c' moved to the end of the word - reaches nothing at all, so the dropdown
stays empty no matter how the results are ranked. Ranking cannot fix that,
because the correct place is never returned in the first place.

So the typed text is compared against a compact index of real place NAMES, and
when one is within a couple of edits it is added to the set of search terms.
The geocoder is still asked that name and is still the only source of the
coordinates, the district, the state and the pincode: this index contains
spellings only, never locations, so nothing about a place is invented here.
"""

from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher

__all__ = ["correct_spelling", "spelling_corrections", "fragment_matches"]


# Real place names, as they are spelled in the map data. Cities, states and the
# larger towns an Indian water-quality user searches for by name. This is a
# SPELLING dictionary, not a location database: it carries no coordinates and no
# water data, so a name here that the geocoders do not know simply returns
# nothing rather than a wrong answer.
_KNOWN_PLACES: tuple[str, ...] = (
    # --- States / union territories ---------------------------------------
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Delhi",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand",
    "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim",
    "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    # --- Cities ------------------------------------------------------------
    "Agartala", "Agra", "Ahmedabad", "Ajmer", "Aligarh", "Allahabad", "Alwar",
    "Amravati", "Amritsar", "Anand", "Anantapur", "Asansol", "Aurangabad", "Ayodhya",
    "Bangalore", "Bareilly", "Bathinda", "Belgaum", "Belgharia", "Bhopal", "Bhilai",
    "Bhubaneswar", "Bikaner", "Bilkas", "Bulandshahr", "Burdwan", "Chandigarh",
    "Chennai", "Chittorgarh", "Coimbatore", "Cuddalore", "Cuttack", "Dabhoi",
    "Dalhousie", "Darjeeling", "Davanagere", "Delhi", "Deoghar", "Dharanadhara",
    "Durgapur", "Erode", "Etawah", "Fatehpur", "Gandhidham", "Gaya", "Ghaziabad",
    "Goa", "Guntur", "Gurdaspur", "Guwahati", "Gwalior", "Haldia", "Haridwar", "Hissar",
    "Hosur", "Howrah", "Hubli", "Hyderabad", "Imphal", "Indore", "Jabalpur", "Jadhavpur",
    "Jalgaon", "Jalandhar", "Jambuguda", "Jamnagar", "Jamshedpur", "Jamnagar", "Jaipur",
    "Jeypore", "Jodhpur", "Kakinada", "Kalimpong", "Kannur", "Kanpur", "Karaikal",
    "Karaikudi", "Karur", "Kasaragod", "Kathmandu", "Katni", "Kollam", "Kota", "Kottayam",
    "Kozhikode", "Kumbakonam", "Kurnool", "Kurukshetra", "Lalitpur", "Leh", "Lucknow",
    "Ludhiana", "Madurai", "Madhugiri", "Mahabaleshwar", "Malda", "Manipal", "Mathura",
    "Meerut", "Mhow", "Moradabad", "Morbi", "Morigaon", "Mumbai", "Muzaffarpur", "Mysore",
    "Nagpur", "Nainital", "Nandyal", "Nashik", "Nellore", "New Delhi", "Neyveli", "Noida",
    "Ooty", "Palakkad", "Palnadu", "Panaji", "Panjim", "Patna", "Pithoragarh", "Pollachi",
    "Pondicherry", "Porbandar", "Port Blair", "Pratapgarh", "Pune", "Puri", "Raichur",
    "Ranchi", "Rao", "Raurkela", "Ravanasamudram", "Razole", "Rourkela", "Sagar",
    "Salem", "Sambalpur", "Satara", "Secunderabad", "Seri", "Shahjahanpur", "Shimla",
    "Shivamogga", "Silchar", "Singrauli", "Sirsa", "Sivakasi", "Solapur", "Srinagar",
    "Surat", "Tehri", "Thanjavur", "Thevaram", "Thiruvananthapuram", "Thrissur", "Tiruchirappalli",
    "Tirunelveli", "Tirupathi", "Tiruppur", "Tiruvallur", "Tiruvottiyur", "Tiruchendur",
    "Tuticorin", "Udhampur", "Ujjain", "Uluberia", "Vadodara", "Varanasi", "Vellore",
    "Vijayawada", "Villupuram", "Visakhapatnam", "Warangal", "Warangal", "Yamunanagar",
    # --- Districts and towns commonly typed on their own --------------------
    "Athur", "Coimbatore", "Dindigul", "Erode", "Karur", "Madurai", "Nagapattinam",
    "Namakkal", "Perambalur", "Pudukkottai", "Ramanathapuram", "Salem", "Sivaganga",
    "Tenkasi", "Thanjavur", "Theni", "Thoothukudi", "Tiruchirappalli", "Tirunelveli",
    "Tiruppur", "Tiruvallur", "Vellore", "Villupuram", "Virudhunagar", "Kottur",
    "Kovilpatti", "Kulasekharam", "Kumbakonam", "Lalgudi", "Manamadurai", "Melur",
    "Oddanchatram", "Papanasam", "Paramakudi", "Periyakulam", "Pollachi", "Rajapalayam",
    "Sivakasi", "Srivilliputhur", "Thiruchengodu", "Tiruchirappalli", "Tiruvallur",
    "Tiruvannamalai", "Tirupathur", "Tiruchiralli", "Usilampatti", "Vadachipuram",
    "Valangaiman", "Vellakoil", "Virudhunagar", "Vriddhachalam", "Mayiladuthurai",
    "Nagercoil", "Thuckalay", "Marakkanandal", "Sathankulam", "Vilavancode", "Kanyakumari",
)


def _fold(value: str) -> str:
    """Lower-case, strip accents, keep only letters and digits."""
    text = "".join(
        ch for ch in unicodedata.normalize("NFKD", str(value or ""))
        if not unicodedata.combining(ch)
    ).lower()
    return "".join(ch for ch in text if ch.isalnum())


def _levenshtein(left: str, right: str) -> int:
    """Edit distance between two short strings, computed in one row."""
    if left == right:
        return 0
    if not left or not right:
        return len(left) or len(right)
    previous = list(range(len(right) + 1))
    for i, lchar in enumerate(left, start=1):
        current = [i]
        for j, rchar in enumerate(right, start=1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (lchar != rchar),
            ))
        previous = current
    return previous[-1]


# The folded name -> the real spelling, built once at import.
_FOLDED_PLACES: dict[str, str] = {}
for _name in _KNOWN_PLACES:
    _folded = _fold(_name)
    # The first spelling wins, so the list's order decides which real name an
    # ambiguous folded form maps to.
    _FOLDED_PLACES.setdefault(_folded, _name)


def spelling_corrections(word: str) -> list[str]:
    """Real spellings close enough to `word` to be what the user meant.

    A hit must be within a small edit distance of the whole word, so a short
    or garbled fragment is never snapped to an unrelated city. The threshold
    tightens as the word grows, because two edits in a four-letter word is
    almost always a different place while one edit in a long word is a typo.

    Returns the correctly spelled names, best first. An empty list means the
    word matches nothing known closely enough, and the caller falls back to the
    geocoders alone.
    """
    folded = _fold(word)
    # Below four characters there is no safe correction: "kar" is one edit from
    # half the index, and snapping it to any of them would be a guess.
    if len(folded) < 4:
        return []

    exact = _FOLDED_PLACES.get(folded)
    if exact:
        return [exact]

    scored: list[tuple[float, str]] = []
    for candidate_folded, candidate in _FOLDED_PLACES.items():
        distance = _levenshtein(folded, candidate_folded)
        # One edit up to five letters, two beyond - the same rule the ranking
        # uses, so a word the index would not correct is not one the ranking
        # would have scored highly either.
        allowed = 1 if len(folded) <= 5 else 2
        if distance > allowed:
            continue
        # Prefer the smallest edit distance, then the closest spelling, then the
        # shorter name, so "chennai" resolves to Chennai rather than to some
        # longer name that happens to be the same distance away.
        ratio = SequenceMatcher(None, folded, candidate_folded).ratio()
        scored.append((-(ratio - 0.05 * distance), candidate))
    scored.sort()
    return [name for _, name in scored]


def fragment_matches(fragment: str, limit: int = 4) -> list[str]:
    """Known place names that CONTAIN `fragment` anywhere inside them.

    This is the case no geocoder can serve. A user types "kudi" part-way through
    "Karaikudi" and neither geocoder will return Karaikudi for it: Open-Meteo
    matches name prefixes and answers with unrelated villages actually named
    "Kudi", and Nominatim does the same. No amount of ranking can help, because
    the place the user wants is never returned at all.

    So the fragment is looked up in the same spelling index and any known place
    name that contains it becomes an extra search term. As with the correction,
    the index only supplies a SPELLING to go and ask the geocoder about - the
    coordinates and the rest of the place still come from the geocoder, so
    nothing about a place is invented.

    Short names come first, because a fragment is far more likely to have been
    typed out of a short name than a long one: "Kudi" is likelier to be what
    someone typing "kudi" meant than "Kudipakkam" is.
    """
    folded = _fold(fragment)
    # Three characters is the floor, so a two-letter fragment matches a
    # meaningless share of the index.
    if len(folded) < 3:
        return []
    matches = [
        (len(_fold(name)), name)
        for name in _FOLDED_PLACES.values()
        if folded in _fold(name)
    ]
    matches.sort()
    seen: set[str] = set()
    return [name for _, name in matches if not (name in seen or seen.add(name))][:limit]


def correct_spelling(text: str) -> str:
    """The query with each word snapped to its real spelling where it is clear.

    Only the FIRST word is corrected. A multi-word query is mostly its first
    word while the user is typing ("hennai amma" -> "Chennai Amma"), and a
    later word that happens to be one edit from some city name is far more
    likely to be a genuine part of the query than a typo. The original text is
    returned unchanged when nothing corrects confidently.

    THE FIRST WORD MEANS THE FIRST WORD THAT HAS A SUGGESTION, not the first
    word of the query. The previous loop walked every part and corrected
    whichever one happened to match something, which meant a perfectly correct
    query was mangled: "Anna Nagar" has no near-miss spelling for "Anna", so the
    loop moved on and found "Nagar" one edit from "Sagar" and rewrote the query
    to "Anna Sagar". The user then got suggestions for a place that does not
    exist, and the real Anna Nagar was never asked about at all. Only part 0 is
    considered now, which is what this function has always claimed to do.
    """
    parts = str(text or "").split()
    if not parts:
        return text

    # Part 0 only - see the note above.
    part = parts[0]
    # A comma marks the end of the place name and the start of a qualifier
    # ("Athur, Madurai"); the bare name is what gets corrected.
    bare = part.split(",")[0]
    if not bare or not any(ch.isalpha() for ch in bare):
        return text
    corrections = spelling_corrections(bare)
    if not corrections:
        return text
    fixed = corrections[0]
    if _fold(fixed) == _fold(bare):
        return text  # already correct
    parts[0] = part.replace(bare, fixed, 1)
    return " ".join(parts)
