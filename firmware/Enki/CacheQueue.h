#pragma once
#include <ArduinoJson.h>

inline void removeConsumedCards(JsonArray cards, JsonArrayConst consumed) {
  for (int i = (int)cards.size() - 1; i >= 0; i--) {
    for (JsonVariantConst id : consumed) {
      if (cards[i]["id"] == id) {
        cards.remove(i);
        break;
      }
    }
  }
}
