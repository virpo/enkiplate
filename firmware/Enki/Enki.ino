// 🪨 enki. Inkplate 4TEMPERA, InkplateLibrary 11.2.1, ArduinoJson 7.
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <Inkplate.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <WiFi.h>
#include <sys/time.h>
#include <time.h>
#include "FrameCodec.h"
#include "CacheQueue.h"

#ifndef ARDUINO_INKPLATE4TEMPERA
#error Select Soldered Inkplate 4TEMPERA
#endif
Inkplate display(INKPLATE_3BIT);
Preferences prefs;
JsonDocument state;
JsonDocument incoming;
bool fetching = false;
int incomingFrame = 0;
uint32_t refillAfter = 0;
String networkError;
struct MetadataRequest {
  String server, token, endpoint;
  uint32_t attempt;
};
struct MetadataResult {
  String body;
  int code;
  uint32_t attempt;
};
QueueHandle_t metadataQueue = nullptr;
bool metadataLoading = false;
uint32_t fetchAttempt = 0;
uint8_t *pixels = nullptr;
bool contextHidden = false, cacheOK = false, usbBatch = false;
bool storageOK = false, journalOK = false, touchOK = false, held = false,
     busy = false;
uint32_t generation = 0, lastTouch = 0, lastNetwork = 0,
         lastUSB = 0, lastBatchAttempt = 0;
String line, deviceId;
constexpr size_t FRAME_BYTES = 180000;
constexpr int MAX_PENDING = 32;
constexpr int CACHE_CARDS = 16;

uint32_t crc32(const uint8_t *data, size_t len) {
  uint32_t crc = 0xffffffff;
  for (size_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (int j = 0; j < 8; j++)
      crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return ~crc;
}
void emit(JsonDocument &doc) {
  serializeJson(doc, Serial);
  Serial.println();
}
void message(const char *key, const char *value) {
  JsonDocument d;
  d[key] = value;
  emit(d);
}
String encodeState() {
  String payload;
  serializeJson(state, payload);
  return payload;
}
String readSlot(const char *key) {
  size_t n = prefs.getBytesLength(key);
  if (!n || n > 48000)
    return "";
  char *buffer = (char *)malloc(n + 1);
  if (!buffer)
    return "";
  size_t received = prefs.getBytes(key, buffer, n);
  buffer[n] = 0;
  String result = received == n ? String(buffer) : String("");
  free(buffer);
  return result;
}
bool saveState() {
  String payload = encodeState();
  JsonDocument box;
  box["generation"] = generation + 1;
  box["payload"] = payload;
  box["crc32"] = crc32((const uint8_t *)payload.c_str(), payload.length());
  String encoded;
  serializeJson(box, encoded);
  const char *slot = ((generation + 1) & 1) ? "stateA" : "stateB";
  if (prefs.putBytes(slot, encoded.c_str(), encoded.length()) !=
          encoded.length() ||
      readSlot(slot) != encoded) {
    message("error", "Could not save review state");
    return false;
  }
  generation++;
  return true;
}
void loadState() {
  for (const char *key : {"stateA", "stateB"}) {
    JsonDocument box, candidate;
    if (deserializeJson(box, readSlot(key)))
      continue;
    String payload = box["payload"] | "";
    if (crc32((const uint8_t *)payload.c_str(), payload.length()) !=
        box["crc32"].as<uint32_t>())
      continue;
    if (deserializeJson(candidate, payload))
      continue;
    uint32_t gen = box["generation"] | 0;
    if (gen > generation) {
      state = candidate;
      generation = gen;
    }
  }
  if (!state["pending"].is<JsonArray>())
    state["pending"].to<JsonArray>();
}
void setClock(uint32_t epoch) {
  if (epoch < 1700000000)
    return;
  timeval tv = {(time_t)epoch, 0};
  settimeofday(&tv, nullptr);
  display.rtc.setEpoch(epoch);
}
String timestamp() {
  time_t epoch = time(nullptr);
  if (epoch < 1700000000)
    return "";
  tm utc;
  gmtime_r(&epoch, &utc);
  char value[30];
  strftime(value, sizeof(value), "%Y-%m-%dT%H:%M:%S+00:00", &utc);
  return value;
}
String pathFor(const String &id) { return "/" + id + ".raw"; }
String compressedPath(const String &id) { return "/" + id + ".z"; }
bool validId(const String &id) {
  if (id.length() != 64)
    return false;
  for (char c : id)
    if (!isxdigit(c))
      return false;
  return true;
}
bool verifyFrame(JsonVariantConst frame) {
  String id = frame["id"] | "";
  if (!validId(id))
    return false;
  File zipped = LittleFS.open(compressedPath(id), "r");
  if (zipped) {
    size_t size = zipped.size();
    uint8_t *buffer = size > 0 && size <= FRAME_BYTES + 1024 ? (uint8_t *)ps_malloc(size) : nullptr;
    bool ok = buffer && zipped.read(buffer, size) == size &&
              inflateFrame(pixels, FRAME_BYTES, buffer, size) &&
              crc32(pixels, FRAME_BYTES) == frame["crc32"].as<uint32_t>();
    free(buffer);
    zipped.close();
    if (ok)
      return true;
  }
  File f = LittleFS.open(pathFor(id), "r");
  if (!f || f.size() != FRAME_BYTES) {
    if (f)
      f.close();
    return false;
  }
  size_t n = f.read(pixels, FRAME_BYTES);
  f.close();
  return n == FRAME_BYTES && crc32(pixels, n) == frame["crc32"].as<uint32_t>();
}
JsonVariant currentCard() {
  int index = state["index"] | 0;
  return state["batch"]["cards"][index];
}
JsonVariant currentFrame() {
  JsonVariant card = currentCard();
  if (card.isNull())
    return state["batch"]["idle"];
  return card[(state["back"] | false) ? "back" : "front"];
}
void note(const char *text) {
  display.clearDisplay();
  display.setTextSize(3);
  display.setTextColor(0);
  display.setCursor(45, 270);
  display.print(text);
  display.display();
}
bool contextExpired() {
  uint32_t rendered = state["batch"]["server_epoch"] | 0;
  uint32_t expires = state["batch"]["context"]["valid_until_epoch"] | 0;
  if (!expires || expires > rendered + 7200)
    expires = rendered + 7200;
  time_t epoch = time(nullptr);
  return !rendered || epoch < 1700000000 || epoch >= expires;
}
void show() {
  if (!storageOK || !pixels)
    return;
  JsonVariant frame = currentFrame();
  if (frame.isNull()) {
    note("Connect enki on your Mac");
    return;
  }
  if (!verifyFrame(frame)) {
    cacheOK = false;
    message("error", "Cached frame missing or damaged");
    note("Reconnect to get this card");
    return;
  }
  display.clearDisplay();
  display.image.drawBitmap3Bit(0, 0, pixels, 600, 600);
  cacheOK = true;
  contextHidden = contextExpired();
  if (contextHidden) {
    display.fillRect(0, 0, 600, 128, 5);
    display.setTextColor(0);
    display.setTextSize(2);
    display.setCursor(30, 45);
    display.print("Context paused.");
  }
  display.display();
  // Require a fresh release after every e-paper refresh, including a finger
  // held on Reveal.
  if (touchOK && display.touchscreen.available()) {
    uint16_t x[2], y[2];
    held = display.touchscreen.getData(x, y) != 0;
  }
  lastTouch = millis();
  message("displayed", (state["back"] | false) ? "back" : "front");
}
void status() {
  JsonDocument d;
  d["status"] = true;
  d["protocol"] = 1;
  d["usb_batch"] = usbBatch;
  d["context_deadline"] = state["batch"]["context"]["valid_until_epoch"] | 0;
  d["context_expired"] = contextExpired();
  d["version"] = "0.2.1";
  d["device_id"] = deviceId;
  d["touch_ok"] = touchOK;
  d["storage_ok"] = storageOK;
  d["journal_ok"] = journalOK;
  d["wifi"] = WiFi.status() == WL_CONNECTED;
  d["ip"] = WiFi.localIP().toString();
  d["pending"] = state["pending"];
  d["remaining"] =
      max(0, (int)state["batch"]["cards"].size() - (state["index"] | 0));
  d["cache_ok"] = cacheOK;
  d["context_epoch"] = state["batch"]["server_epoch"] | 0;
  d["fetching"] = fetching;
  d["network_error"] = networkError;
  d["cache_capacity"] = CACHE_CARDS;
  d["fs_used"] = LittleFS.usedBytes();
  d["fs_total"] = LittleFS.totalBytes();
  JsonArray ids = d["cards"].to<JsonArray>();
  JsonArray frames = d["frames"].to<JsonArray>();
  int index = state["index"] | 0;
  int i = 0;
  for (JsonVariant card : state["batch"]["cards"].as<JsonArray>()) {
    if (i++ >= index)
      ids.add(card["id"]);
    frames.add(card["front"]["id"]);
    frames.add(card["back"]["id"]);
  }
  if (!state["batch"]["idle"].isNull())
    frames.add(state["batch"]["idle"]["id"]);
  d["back"] = state["back"] | false;
  d["card_id"] = currentCard()["id"];
  d["epoch"] = (uint32_t)time(nullptr);
  emit(d);
}
String batchSignature(JsonVariantConst batch) {
  String result = batch["idle"]["id"] | "";
  for (JsonVariantConst card : batch["cards"].as<JsonArrayConst>()) {
    result += card["id"].as<String>();
    result += card["front"]["id"].as<String>();
    result += card["back"]["id"].as<String>();
  }
  return result;
}
bool installBatch(JsonVariantConst batch) {
  if (batch["protocol"] != 1 || batch["cards"].size() > CACHE_CARDS)
    return false;
  for (JsonVariantConst card : batch["cards"].as<JsonArrayConst>())
    if (!verifyFrame(card["front"]) || !verifyFrame(card["back"]))
      return false;
  if (batch["cards"].size() == 0 && !verifyFrame(batch["idle"]))
    return false;
  bool same = cacheOK && (state["index"] | 0) == 0 &&
              !(state["back"] | false) &&
              batchSignature(state["batch"]) == batchSignature(batch);
  if (same) {
    bool deadlineChanged = state["batch"]["context"]["valid_until_epoch"] !=
                           batch["context"]["valid_until_epoch"];
    bool revisionChanged = state["batch"]["study_revision"] != batch["study_revision"];
    state["batch"]["context"] = batch["context"];
    state["batch"]["server_epoch"] = batch["server_epoch"];
    state["batch"]["study_revision"] = batch["study_revision"];
    if ((deadlineChanged || revisionChanged) && !saveState())
      return false;
    setClock(batch["clock_epoch"] | batch["server_epoch"].as<uint32_t>());
    if (contextHidden)
      show();
    return true;
  }
  bool hadCache = cacheOK;
  bool resume = (batch["resume_back"] | false) &&
                currentCard()["id"] == batch["cards"][0]["id"];
  String oldId = currentFrame()["id"] | "";
  String before = encodeState();
  state["batch"] = batch;
  state["index"] = 0;
  state["back"] = resume;
  if (!saveState()) {
    deserializeJson(state, before);
    return false;
  }
  setClock(batch["clock_epoch"] | batch["server_epoch"].as<uint32_t>());
  cacheOK = true;
  if (oldId != (currentFrame()["id"] | String("")) || contextHidden ||
      !hadCache)
    show();
  return true;
}
void garbageCollect() {
  // Only remove renderer frame files. Keep both current sides; queued reviews
  // live in NVS.
  File root = LittleFS.open("/");
  File file = root.openNextFile();
  while (file) {
    String name = String(file.name());
    file.close();
    if (!name.startsWith("/"))
      name = "/" + name;
    bool keep = false;
    int index = 0;
    for (JsonVariant card : state["batch"]["cards"].as<JsonArray>()) {
      if (index++ < (state["index"] | 0))
        continue;
      for (const char *side : {"front", "back"})
        if (name == pathFor(card[side]["id"] | "") || name == compressedPath(card[side]["id"] | ""))
          keep = true;
    }
    if (name == pathFor(state["batch"]["idle"]["id"] | "") || name == compressedPath(state["batch"]["idle"]["id"] | ""))
      keep = true;
    if (!keep && (name.endsWith(".raw") || name.endsWith(".z") || name.endsWith(".tmp")))
      LittleFS.remove(name);
    file = root.openNextFile();
  }
  root.close();
}
void acknowledge(JsonArrayConst ids) {
  String before = encodeState();
  JsonArray pending = state["pending"].as<JsonArray>();
  for (int i = (int)pending.size() - 1; i >= 0; i--)
    for (JsonVariantConst id : ids)
      if (pending[i]["id"] == id) {
        pending.remove(i);
        break;
      }
  if (!saveState())
    deserializeJson(state, before);
}
void tap(int x, int y) {
  if (busy || usbBatch || !cacheOK || !storageOK || currentCard().isNull())
    return;
  bool back = state["back"] | false;
  JsonVariant frame = currentFrame();
  for (JsonVariant hit : frame["hits"].as<JsonArray>()) {
    int hx = hit["x"], hy = hit["y"], w = hit["w"], h = hit["h"];
    if (x < hx || x >= hx + w || y < hy || y >= hy + h)
      continue;
    busy = true;
    String before = encodeState();
    if (!back) {
      state["back"] = true;
      if (saveState())
        show();
      else
        deserializeJson(state, before);
    } else {
      if (state["pending"].size() >= MAX_PENDING) {
        message("error", "Review queue full. Reconnect before grading.");
        busy = false;
        return;
      }
      JsonObject event = state["pending"].add<JsonObject>();
      char id[70];
      snprintf(id, sizeof(id), "%s:%08lx%08lx", deviceId.c_str(),
               (unsigned long)esp_random(), (unsigned long)esp_random());
      event["id"] = id;
      event["card_id"] = currentCard()["id"];
      event["device_id"] = deviceId;
      event["rating"] = hit["rating"];
      String at = timestamp();
      if (at.length())
        event["reviewed_at"] = at;
      else
        event["reviewed_at"] = nullptr;
      String answeredId = currentCard()["id"] | "";
      state["index"] = (state["index"] | 0) + 1;
      state["back"] = false;
      if (saveState()) {
        if (fetching)
          incoming["consumed"].add(answeredId);
        JsonDocument d;
        d["event"] = event;
        emit(d);
        if (!currentCard().isNull())
          show();
        else {
          if (!fetching && !state["batch"]["idle"].isNull())
            show();
          else
            note(WiFi.status() == WL_CONNECTED ? "Getting cards..." : "Offline. Reconnecting...");
          lastNetwork = millis() - 15000;
          lastBatchAttempt = millis() - 60000;
          refillAfter = millis();
          message("need_batch", "true");
        }
      } else
        deserializeJson(state, before);
    }
    busy = false;
    return;
  }
}
String urlEncode(const String &value) {
  const char *hex = "0123456789ABCDEF";
  String out;
  for (size_t i = 0; i < value.length(); i++) {
    uint8_t c = value[i];
    if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
        (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.' || c == '~')
      out += (char)c;
    else {
      out += '%';
      out += hex[c >> 4];
      out += hex[c & 15];
    }
  }
  return out;
}
HTTPClient http;
bool beginRequest(const String &path) {
  String server = prefs.getString("server");
  if (!server.startsWith("http://"))
    return false;
  if (!http.begin(server + path))
    return false;
  http.setConnectTimeout(2000);
  http.setTimeout(7000);
  http.addHeader("Authorization", "Bearer " + prefs.getString("token"));
  http.addHeader("X-Enki-Device", deviceId);
  http.addHeader("X-Enki-Style", state["batch"]["display_style"] | "cutout");
  http.addHeader("X-Enki-Revision", String(state["batch"]["study_revision"].as<uint32_t>()));
  http.addHeader("X-Enki-Remaining", String(max(0, (int)state["batch"]["cards"].size() - (state["index"] | 0))));
  http.addHeader("X-Enki-Pending", String(state["pending"].size()));
  http.addHeader("X-Enki-Fetching", fetching ? "1" : "0");
  http.addHeader("X-Enki-Error", networkError);
  http.addHeader("X-Enki-Firmware", "0.2.1");
  http.addHeader("X-Enki-Uptime", String(millis() / 1000));
  http.addHeader("X-Enki-Frame", currentFrame()["id"] | "");
  http.addHeader("X-Enki-Fs-Used", String(LittleFS.usedBytes()));
  return true;
}
bool downloadFrame(JsonVariantConst frame) {
  if (verifyFrame(frame))
    return true;
  String id = frame["id"] | "";
  bool compressed = !frame["compressed"].isNull();
  size_t expected = compressed ? frame["compressed_bytes"].as<size_t>() : FRAME_BYTES;
  if (!expected || expected > FRAME_BYTES + 1024 || !validId(id) ||
      !beginRequest(frame[compressed ? "compressed" : "raw"] | ""))
    return false;
  int code = http.GET();
  if (code != 200 || http.getSize() != expected) {
    networkError = "Frame HTTP " + String(code);
    http.end();
    return false;
  }
  WiFiClient *stream = http.getStreamPtr();
  uint8_t *buffer = compressed ? (uint8_t *)ps_malloc(expected) : pixels;
  if (!buffer) {
    http.end();
    networkError = "Frame memory unavailable";
    return false;
  }
  size_t n = stream->readBytes(buffer, expected);
  http.end();
  bool ok = n == expected && (!compressed || inflateFrame(pixels, FRAME_BYTES, buffer, n)) &&
            crc32(pixels, FRAME_BYTES) == frame["crc32"].as<uint32_t>();
  if (!ok) {
    if (compressed)
      free(buffer);
    networkError = "Incomplete or damaged frame";
    return false;
  }
  String target = compressed ? compressedPath(id) : pathFor(id);
  String temporary = "/download.tmp";
  File f = LittleFS.open(temporary, "w");
  if (!f) {
    if (compressed)
      free(buffer);
    networkError = "Frame storage full";
    return false;
  }
  size_t written = f.write(buffer, n);
  f.close();
  if (compressed)
    free(buffer);
  ok = written == n && LittleFS.rename(temporary, target) && verifyFrame(frame);
  if (!ok)
    networkError = "Frame storage failed";
  return ok;
}
bool flushReviews() {
  if (state["pending"].size() == 0)
    return true;
  if (!beginRequest("/api/reviews"))
    return false;
  JsonDocument request;
  request["events"] = state["pending"];
  String body;
  serializeJson(request, body);
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(body);
  String result = http.getString();
  http.end();
  JsonDocument reply;
  if (deserializeJson(reply, result))
    return false;
  JsonDocument ids;
  JsonArray list = ids.to<JsonArray>();
  for (JsonVariant accepted : reply["accepted"].as<JsonArray>())
    list.add(accepted["id"]);
  for (JsonVariant rejected : reply["rejected"].as<JsonArray>())
    list.add(rejected["id"]);
  acknowledge(list);
  return code == 200 && state["pending"].size() == 0;
}
void cancelIncoming() {
  fetching = false;
  incomingFrame = 0;
  incoming.clear();
}
void fetchMetadata(void *argument) {
  MetadataRequest *request = (MetadataRequest *)argument;
  MetadataResult *result = new MetadataResult;
  result->attempt = request->attempt;
  result->code = -1;
  HTTPClient client;
  if (client.begin(request->server + request->endpoint)) {
    client.setConnectTimeout(2000);
    client.setTimeout(30000);
    client.addHeader("Authorization", "Bearer " + request->token);
    result->code = client.GET();
    if (result->code == 200)
      result->body = client.getString();
    client.end();
  }
  delete request;
  xQueueSend(metadataQueue, &result, portMAX_DELAY);
  vTaskDelete(nullptr);
}
void acceptMetadata() {
  MetadataResult *result = nullptr;
  if (!metadataQueue || xQueueReceive(metadataQueue, &result, 0) != pdTRUE)
    return;
  metadataLoading = false;
  if (!fetching || result->attempt != fetchAttempt) {
    delete result;
    return;
  }
  JsonDocument consumed;
  consumed.set(incoming["consumed"]);
  if (result->code == 200 && !deserializeJson(incoming, result->body) &&
      incoming["protocol"] == 1 && incoming["cards"].size() <= CACHE_CARDS) {
    incoming["consumed"] = consumed;
    garbageCollect();
    incomingFrame = 0;
    networkError = "";
  } else {
    networkError = "Study HTTP " + String(result->code);
    message("network_error", networkError.c_str());
    cancelIncoming();
    refillAfter = millis() + 15000;
  }
  delete result;
}
void receiveNextFrame() {
  // One compressed frame per loop, returning to touch handling between frames.
  int count = incoming["cards"].size();
  JsonVariantConst frame = incomingFrame < count * 2
      ? incoming["cards"][incomingFrame / 2][incomingFrame % 2 ? "back" : "front"].as<JsonVariantConst>()
      : incoming["idle"].as<JsonVariantConst>();
  if (!frame.isNull() && !downloadFrame(frame)) {
    message("network_error", networkError.c_str());
    cancelIncoming();
    refillAfter = millis() + 15000;
    garbageCollect();
    if (currentCard().isNull())
      note("Offline. Reconnecting...");
    return;
  }
  incomingFrame++;
  if (incomingFrame <= count * 2)
    return;
  JsonArray cards = incoming["cards"].as<JsonArray>();
  // A person may have graded while the rest of this queue was downloading.
  // Never reinsert those cards, including answers already acknowledged online.
  removeConsumedCards(cards, incoming["consumed"].as<JsonArrayConst>());
  incoming.remove("consumed");
  incoming["resume_back"] = state["back"] | false;
  incoming["clock_epoch"] = (uint32_t)time(nullptr);
  int remaining = max(0, (int)state["batch"]["cards"].size() - (state["index"] | 0));
  bool gained = cards.size() > remaining;
  if (installBatch(incoming.as<JsonVariantConst>())) {
    networkError = "";
    message("cache_ready", String(cards.size()).c_str());
  } else {
    networkError = "Could not commit card cache";
    message("network_error", networkError.c_str());
  }
  cancelIncoming();
  refillAfter = millis() + (gained ? 15000 : 60000);
  garbageCollect();
  // Report the committed queue promptly, including when no more cards are due.
  lastNetwork = millis() - 15000;
}
void networkTick() {
  acceptMetadata();
  if (usbBatch && millis() - lastUSB >= 60000)
    usbBatch = false;
  if (!prefs.getString("ssid").length() || busy || usbBatch ||
      millis() - lastUSB < 10000)
    return;
  if (WiFi.status() != WL_CONNECTED) {
    if (fetching) {
      cancelIncoming();
      networkError = "Wi-Fi disconnected";
    }
    if (millis() - lastNetwork > 30000) {
      lastNetwork = millis();
      WiFi.begin(prefs.getString("ssid").c_str(),
                 prefs.getString("password").c_str());
    }
    return;
  }
  if (fetching) {
    if (!metadataLoading)
      receiveNextFrame();
    return;
  }
  if (metadataLoading)
    return;
  if (millis() - lastNetwork < 15000)
    return;
  lastNetwork = millis();
  busy = true;
  bool synced = flushReviews();
  bool curriculumChanged = false;
  if (synced && beginRequest("/api/time")) {
    http.setConnectTimeout(1000);
    http.setTimeout(1500);
    int code = http.GET();
    JsonDocument info;
    if (code == 200 && !deserializeJson(info, http.getString()) &&
        info["study_revision"].is<uint32_t>()) {
      curriculumChanged = info["study_revision"].as<uint32_t>() !=
                          state["batch"]["study_revision"].as<uint32_t>();
      setClock(info["epoch"] | 0);
    }
    http.end();
  }
  int remaining = max(0, (int)state["batch"]["cards"].size() - (state["index"] | 0));
  bool readyToRefill = (int32_t)(millis() - refillAfter) >= 0;
  bool refill = remaining <= 6 && readyToRefill;
  bool refresh =
      (contextExpired() ||
       time(nullptr) >= (state["batch"]["server_epoch"] | 0) + 600) &&
      !(state["back"] | false);
  bool repair = !cacheOK && !currentFrame().isNull();
  String endpoint = "/api/study?count=" + String(CACHE_CARDS);
  int i = 0, index = state["index"] | 0;
  for (JsonVariant card : state["batch"]["cards"].as<JsonArray>()) {
    if (i++ >= index)
      endpoint += "&keep=" + urlEncode(card["id"] | "");
  }
  if (synced && (refill || refresh || repair || curriculumChanged) && metadataQueue) {
    lastBatchAttempt = millis();
    incoming.clear();
    incoming["consumed"].to<JsonArray>();
    fetching = true;
    metadataLoading = true;
    MetadataRequest *request = new MetadataRequest{
      prefs.getString("server"), prefs.getString("token"), endpoint, ++fetchAttempt};
    if (xTaskCreate(fetchMetadata, "enki-cards", 8192, request, 1, nullptr) != pdPASS) {
      delete request;
      metadataLoading = false;
      cancelIncoming();
      networkError = "Network task unavailable";
      refillAfter = millis() + 15000;
    }
  }
  busy = false;
}

void command(JsonDocument &cmd) {
  lastUSB = millis();
  String op = cmd["cmd"] | "";
  if (op == "status")
    status();
  else if (op == "tap") {
    tap(cmd["x"] | 0, cmd["y"] | 0);
    status();
  } else if (op == "ack") {
    acknowledge(cmd["ids"].as<JsonArrayConst>());
    message("ack", "ok");
  } else if (op == "abort") {
    usbBatch = false;
    garbageCollect();
    message("aborted", "ok");
  } else if (op == "prepare") {
    cancelIncoming();
    usbBatch = true;
    garbageCollect();
    message("prepared", "ok");
    status();
  } else if (op == "batch") {
    bool ok = installBatch(cmd["batch"]);
    usbBatch = false;
    if (ok)
      garbageCollect();
    message("installed", ok ? "ok" : "failed");
  } else if (op == "config") {
    if (!journalOK) {
      message("error", "Review storage did not initialise");
      return;
    }
    String server = cmd["server"] | "", ssid = cmd["ssid"] | "",
           password = cmd["password"] | "", token = cmd["token"] | "";
    if (!server.startsWith("http://") || ssid.length() > 32 || !ssid.length() ||
        password.length() > 63 || token.length() < 32) {
      message("error", "Invalid configuration");
      return;
    }
    prefs.putString("server", server);
    prefs.putString("ssid", ssid);
    prefs.putString("password", password);
    prefs.putString("token", token);
    setClock(cmd["epoch"] | 0);
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid.c_str(), password.c_str());
    message("configured", "ok");
  } else if (op == "frame") {
    String id = cmd["id"] | "";
    uint32_t expected = cmd["crc32"].as<uint32_t>();
    if (!validId(id) || cmd["length"] != FRAME_BYTES || !pixels || !storageOK) {
      message("error", "Invalid frame header");
      return;
    }
    message("ready", id.c_str());
    Serial.setTimeout(15000);
    size_t n = Serial.readBytes(pixels, FRAME_BYTES);
    if (n != FRAME_BYTES || crc32(pixels, n) != expected) {
      usbBatch = false;
      JsonDocument error;
      error["error"] = "Incomplete frame or CRC mismatch";
      error["received_bytes"] = n;
      error["expected_bytes"] = FRAME_BYTES;
      error["crc32"] = crc32(pixels, n);
      error["expected_crc32"] = expected;
      emit(error);
      return;
    }
    String target = pathFor(id), temp = target + ".tmp";
    // Atomic replacement keeps the committed frame intact if USB or power
    // fails.
    File f = LittleFS.open(temp, "w");
    if (!f) {
      message("error", "Storage full");
      return;
    }
    size_t written = f.write(pixels, n);
    f.close();
    if (written == n && LittleFS.rename(temp, target))
      message("stored", id.c_str());
    else
      message("error", "Frame write failed");
  }
}
void setup() {
  Serial.begin(115200);
  Serial.setTimeout(100);
  lastBatchAttempt = millis() - 60000;
  display.begin();
  pixels = (uint8_t *)ps_malloc(FRAME_BYTES);
  journalOK = prefs.begin("enki", false, "enki_nvs");
  metadataQueue = xQueueCreate(1, sizeof(MetadataResult *));
  deviceId = "inkplate-" + String((uint32_t)ESP.getEfuseMac(), HEX);
  loadState();
  bool filesOK = LittleFS.begin(false);
  if (!filesOK)
    filesOK = LittleFS.begin(true);
  storageOK = filesOK && journalOK;
  touchOK = display.touchscreen.init(true);
  setClock(display.rtc.getEpoch());
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  if (prefs.getString("ssid").length())
    WiFi.begin(prefs.getString("ssid").c_str(),
               prefs.getString("password").c_str());
  if (!pixels)
    note("Display memory unavailable");
  else if (!storageOK)
    note("Storage unavailable");
  else
    show();
  status();
}
void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      JsonDocument cmd;
      if (!deserializeJson(cmd, line))
        command(cmd);
      lastUSB = millis();
      line = "";
    } else if (line.length() < 20000)
      line += c;
    else
      line = "";
  }
  if (touchOK && display.touchscreen.available()) {
    uint16_t x[2], y[2];
    uint8_t n = display.touchscreen.getData(x, y);
    if (n == 0) {
      held = false;
      lastTouch = millis();
    } else if (!held && n == 1 && millis() - lastTouch > 180) {
      held = true;
      message("touch", "down");
      tap(x[0], y[0]);
    }
  }
  networkTick();
  if (!busy && cacheOK && !contextHidden && !currentFrame().isNull() &&
      contextExpired())
    show();
  delay(10);
}
