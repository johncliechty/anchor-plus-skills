export const venueWhitelistSchema = {
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "VenueWhitelist",
  "type": "object",
  "required": ["venues"],
  "properties": {
    "venues": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "abbr", "tier"],
        "properties": {
          "name": { "type": "string" },
          "abbr": { "type": "string" },
          "tier": { "type": "string", "enum": ["Tier-1", "Tier-2", "Tier-3"] }
        }
      }
    }
  }
};
