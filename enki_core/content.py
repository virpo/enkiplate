from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

from pykakasi import kakasi

ROMANIZER = kakasi()

# Common written forms, paired with the particular kana word and sense taught.
# Leave loanwords and expressions normally written in kana alone.
WORD_KANJI = {
    "ねこ": "猫",
    "いぬ": "犬",
    "やま": "山",
    "かわ": "川",
    "みず": "水",
    "ほん": "本",
    "がっこう": "学校",
    "きって": "切手",
    "きょう": "今日",
    "おちゃ": "お茶",
    "でんしゃ": "電車",
    "えき": "駅",
    "くるま": "車",
    "さかな": "魚",
    "でんわ": "電話",
    "ねる": "寝る",
    "たべる": "食べる",
    "よむ": "読む",
    "あるく": "歩く",
    "あか": "赤",
    "しろ": "白",
    "くろ": "黒",
    "おおきい": "大きい",
    "ちいさい": "小さい",
    "まって": "待って",
}


def romanize(reading: str) -> str:
    """Hepburn-style ASCII. Long vowels remain explicit: gakkou, koohii."""
    return "".join(part["hepburn"] for part in ROMANIZER.convert(reading))


def builtin_cards() -> list[dict]:
    rows: list[dict] = []
    base = [
        ("あいうえお", "a i u e o"),
        ("かきくけこ", "ka ki ku ke ko"),
        ("さしすせそ", "sa shi su se so"),
        ("たちつてと", "ta chi tsu te to"),
        ("なにぬねの", "na ni nu ne no"),
        ("はひふへほ", "ha hi fu he ho"),
        ("まみむめも", "ma mi mu me mo"),
        ("やゆよ", "ya yu yo"),
        ("らりるれろ", "ra ri ru re ro"),
        ("わをん", "wa wo n"),
    ]
    voiced = [
        ("がぎぐげご", "ga gi gu ge go"),
        ("ざじずぜぞ", "za ji zu ze zo"),
        ("だぢづでど", "da ji zu de do"),
        ("ばびぶべぼ", "ba bi bu be bo"),
        ("ぱぴぷぺぽ", "pa pi pu pe po"),
    ]
    combinations = []
    for stem, root in [
        ("き", "ky"),
        ("し", "sh"),
        ("ち", "ch"),
        ("に", "ny"),
        ("ひ", "hy"),
        ("み", "my"),
        ("り", "ry"),
        ("ぎ", "gy"),
        ("じ", "j"),
        ("び", "by"),
        ("ぴ", "py"),
    ]:
        for small, vowel in [("ゃ", "a"), ("ゅ", "u"), ("ょ", "o")]:
            combinations.append((stem + small, root + vowel))
    for script in ("hira", "kata"):
        for group, grouped in enumerate((base, voiced)):
            for chars, readings in grouped:
                for jp, romaji in zip(chars, readings.split(), strict=True):
                    shown = jp if script == "hira" else chr(ord(jp) + 0x60)
                    rows.append(
                        dict(
                            id=f"kana:{script}:{jp}",
                            jp=shown,
                            reading=romaji,
                            meaning="",
                            kind="kana",
                            stage=group,
                            source="curated",
                            ordinal=len(rows),
                        )
                    )
        for jp, reading in combinations:
            shown = jp if script == "hira" else "".join(chr(ord(c) + 0x60) for c in jp)
            rows.append(
                dict(
                    id=f"kana:{script}:{jp}",
                    jp=shown,
                    reading=reading,
                    meaning="",
                    kind="kana",
                    stage=1,
                    source="curated",
                    ordinal=len(rows),
                )
            )
    # Verified words reinforce small tsu, vowel length, voiced kana and useful everyday readings.
    words = [
        ("ねこ", "ねこ", "cat"),
        ("いぬ", "いぬ", "dog"),
        ("やま", "やま", "mountain"),
        ("かわ", "かわ", "river"),
        ("みず", "みず", "water"),
        ("ほん", "ほん", "book"),
        ("カメラ", "カメラ", "camera"),
        ("コーヒー", "コーヒー", "coffee"),
        ("がっこう", "がっこう", "school"),
        ("きって", "きって", "postage stamp"),
        ("きょう", "きょう", "today"),
        ("おちゃ", "おちゃ", "tea"),
        ("でんしゃ", "でんしゃ", "train"),
        ("えき", "えき", "station"),
        ("くるま", "くるま", "car"),
        ("バス", "バス", "bus"),
        ("タクシー", "タクシー", "taxi"),
        ("パン", "パン", "bread"),
        ("スーパー", "スーパー", "supermarket"),
        ("アイス", "アイス", "ice; ice cream"),
        ("りんご", "りんご", "apple"),
        ("ありがとう", "ありがとう", "thank you"),
        ("おはよう", "おはよう", "good morning"),
        ("こんにちは", "こんにちは", "hello"),
        ("さかな", "さかな", "fish"),
        ("でんわ", "でんわ", "telephone"),
        ("ねる", "ねる", "to sleep"),
        ("たべる", "たべる", "to eat"),
        ("よむ", "よむ", "to read"),
        ("あるく", "あるく", "to walk"),
        ("あか", "あか", "red"),
        ("しろ", "しろ", "white"),
        ("くろ", "くろ", "black"),
        ("おおきい", "おおきい", "big"),
        ("ちいさい", "ちいさい", "small"),
        ("まって", "まって", "wait"),
    ]
    advanced = [
        ("読む", "よむ", "to read"),
        ("電車", "でんしゃ", "train"),
        ("学校", "がっこう", "school"),
        ("駅", "えき", "station"),
        ("水", "みず", "water"),
        ("山", "やま", "mountain"),
        ("川", "かわ", "river"),
        ("本", "ほん", "book"),
        ("犬", "いぬ", "dog"),
        ("猫", "ねこ", "cat"),
        ("車", "くるま", "car"),
        ("食べる", "たべる", "to eat"),
        ("歩く", "あるく", "to walk"),
        ("行く", "いく", "to go"),
        ("雨", "あめ", "rain"),
        ("雪", "ゆき", "snow"),
        ("空", "そら", "sky"),
        ("大きい", "おおきい", "big"),
        ("小さい", "ちいさい", "small"),
        ("今日", "きょう", "today"),
        ("明日", "あした", "tomorrow"),
        ("日本", "にほん", "Japan (also read nippon)"),
        ("日本語", "にほんご", "Japanese language"),
        ("朝", "あさ", "morning"),
        ("夜", "よる", "night"),
    ]
    for stage, values in [(2, words), (3, advanced)]:
        for jp, kana, meaning in values:
            # The greeting's は is pronounced wa.
            reading = "konnichiwa" if jp == "こんにちは" else romanize(kana)
            rows.append(
                dict(
                    id=f"curated:{jp}",
                    jp=jp,
                    reading=reading,
                    meaning=meaning,
                    kanji=WORD_KANJI.get(jp, "") if stage == 2 else "",
                    kind="word",
                    stage=stage,
                    source="curated",
                    ordinal=len(rows),
                )
            )
    for jp, reading in [
        ("ヴ", "vu"),
        ("ファ", "fa"),
        ("フィ", "fi"),
        ("フェ", "fe"),
        ("フォ", "fo"),
        ("ティ", "ti"),
        ("ディ", "di"),
        ("トゥ", "tu"),
        ("ドゥ", "du"),
        ("チェ", "che"),
        ("シェ", "she"),
        ("ジェ", "je"),
        ("ウィ", "wi"),
        ("ウェ", "we"),
        ("ウォ", "wo"),
        ("ヴァ", "va"),
        ("ヴィ", "vi"),
        ("ヴェ", "ve"),
        ("ヴォ", "vo"),
    ]:
        rows.append(
            dict(
                id=f"kana:extended:{jp}",
                jp=jp,
                reading=reading,
                meaning="",
                kind="kana",
                stage=1,
                source="curated",
                ordinal=len(rows),
            )
        )
    sentences = [
        ("これは何ですか。", "kore wa nan desu ka.", "What is this?"),
        ("駅はどこですか。", "eki wa doko desu ka.", "Where is the station?"),
        ("水をください。", "mizu o kudasai.", "Water, please."),
        ("日本語を勉強しています。", "nihongo o benkyou shite imasu.", "I am studying Japanese."),
        (
            "明日は電車で京都に行きます。",
            "ashita wa densha de kyouto ni ikimasu.",
            "Tomorrow, I will go to Kyoto by train.",
        ),
    ]
    for jp, reading, meaning in sentences:
        rows.append(
            dict(
                id=f"sentence:{jp}",
                jp=jp,
                reading=reading,
                meaning=meaning,
                kind="sentence",
                stage=4,
                source="curated",
                ordinal=len(rows),
            )
        )
    return rows


def seed(connection: sqlite3.Connection) -> int:
    rows = builtin_cards()
    for row in rows:
        row.setdefault("kanji", "")
    connection.executemany(
        "INSERT INTO cards(id,jp,reading,meaning,kind,stage,source,ordinal,kanji) "
        "VALUES(:id,:jp,:reading,:meaning,:kind,:stage,:source,:ordinal,:kanji) "
        "ON CONFLICT(id) DO UPDATE SET kanji=excluded.kanji WHERE cards.source='curated'",
        rows,
    )
    return len(rows)


def import_jmdict(connection: sqlite3.Connection, path: Path, limit: int = 12000) -> int:
    """Import common, unambiguous English JMdict entries without altering review history."""
    xml_lang = "{http://www.w3.org/XML/1998/namespace}lang"
    common = {"news1", "ichi1", "spec1", "gai1"}
    count = 0
    with gzip.open(path, "rb") as stream:
        for _, entry in ET.iterparse(stream, events=("end",)):
            if entry.tag != "entry":
                continue
            spellings = entry.findall("k_ele")
            if not spellings:
                entry.clear()
                continue
            chosen = next(
                (s for s in spellings if common.intersection(n.text for n in s.findall("ke_pri"))),
                None,
            )
            if chosen is None:
                entry.clear()
                continue
            jp = chosen.findtext("keb", "")
            readings = [
                r
                for r in entry.findall("r_ele")
                if r.find("re_nokanji") is None
                and (not r.findall("re_restr") or jp in [n.text for n in r.findall("re_restr")])
            ]
            if len(readings) != 1 or not 1 <= len(jp) <= 10:
                entry.clear()
                continue
            kana = readings[0].findtext("reb", "")
            glosses = []
            for sense in entry.findall("sense"):
                if sense.findall("stagk") and jp not in [n.text for n in sense.findall("stagk")]:
                    continue
                if sense.findall("stagr") and kana not in [n.text for n in sense.findall("stagr")]:
                    continue
                if sense.findall("misc"):
                    # Exclude obsolete, obscure, vulgar and other marked senses from unattended growth.
                    continue
                glosses.extend(
                    g.text
                    for g in sense.findall("gloss")
                    if g.get(xml_lang, "eng") == "eng" and g.text
                )
            if not glosses or not kana:
                entry.clear()
                continue
            short = [g for g in dict.fromkeys(glosses) if len(g) <= 110]
            if not short:
                entry.clear()
                continue
            chosen_glosses = [short[0]]
            for gloss in short[1:3]:
                if len("; ".join(chosen_glosses + [gloss])) <= 145:
                    chosen_glosses.append(gloss)
            meaning = "; ".join(chosen_glosses)
            identity = "jmdict:" + entry.findtext("ent_seq", "")
            connection.execute(
                "INSERT INTO cards(id,jp,reading,meaning,kind,stage,source,ordinal) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "jp=excluded.jp,reading=excluded.reading,meaning=excluded.meaning",
                (
                    identity,
                    unicodedata.normalize("NFC", jp),
                    romanize(kana),
                    meaning,
                    "word",
                    4,
                    "JMdict / EDRDG",
                    10000 + count,
                ),
            )
            count += 1
            entry.clear()
            if count >= limit:
                break
    return count


def content_hash(card: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            {k: card[k] for k in ("jp", "reading", "meaning")},
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()[:20]
