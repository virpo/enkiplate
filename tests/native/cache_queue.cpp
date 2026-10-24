#include "CacheQueue.h"
#include <cassert>
#include <string>

int main() {
  JsonDocument batch;
  JsonArray cards = batch["cards"].to<JsonArray>();
  for (int i = 0; i < 16; i++)
    cards.add<JsonObject>()["id"] = "word-" + std::to_string(i);
  JsonArray consumed = batch["consumed"].to<JsonArray>();
  // Two grades land during prefetch. Acknowledgements may already have removed
  // them from the pending review journal, so the fetch keeps its own record.
  consumed.add("word-0");
  consumed.add("word-1");
  consumed.add("word-0");
  consumed.add("a-card-not-in-this-batch");
  removeConsumedCards(cards, consumed);
  assert(cards.size() == 14);
  for (int i = 0; i < 14; i++)
    assert(cards[i]["id"].as<std::string>() == "word-" + std::to_string(i + 2));
  removeConsumedCards(cards, consumed);
  assert(cards.size() == 14);
  for (int i = 2; i < 16; i++)
    consumed.add("word-" + std::to_string(i));
  removeConsumedCards(cards, consumed);
  assert(cards.size() == 0); // Finishing the old queue cannot replay its cards.
}
