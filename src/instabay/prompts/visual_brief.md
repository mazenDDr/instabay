# Evidence-first brief — FR-04, FR-06

Produce ONE JSON INSTANCE, not a schema. Do not repeat $defs, properties, required or types.
Return brief, media_ids, fact_ids, pillar_intent, sequence_reason and cta_kind.
Read post_format first. For photo, media_ids has EXACTLY ONE element and the brief describes
ONLY that photograph. For carousel, select multiple photographs. For reel, select three
to five scenes. This request is for ONE post, not the entire week or all available scenes.
The supplied scenes and visual facts are the available story. Never invent a facility,
room interior, underwater view, species, price, deal, availability or guest testimonial.
Historical photos are not proof of current condition. Do not describe Maldives references
as Hurghada, the Red Sea, or fictional Insta Bay facilities. Name their actual source property.

Keep the slot's pillar and format. Read evidence.pillar_guidance for that pillar. Give the
post a distinct, concrete angle and one useful viewer action. previous_angles are already
used this week: avoid repeating them or simply saying "slow down" in every post.

Photo: choose exactly one scene and one vivid, specific thought drawn from it.
Carousel: choose 2–5 DIFFERENT photographs, ordered as a mini exploration or a useful
comparison. Explain the progression in sequence_reason. Do not make repeated crops of one
image. The caption will carry the sequence; no text panels are required over the images.
Reel: choose 3–5 complete coastal/property scenes. The video will show gentle continuous
motion in each scene, normally five seconds each. Describe a readable place with water,
shoreline, palms or buildings. No rapid object montage or manual start/end keyframes.

media_ids must be exact scene IDs. fact_ids must be exact supplied fact IDs, including at
least one fact from EACH selected scene. brief.photo_uri is the first selected source's
exact photo_uri. All brief fields are strings except must_not and reel_concept.
reel_concept is null for photo/carousel. For a reel it has hook, shots (semantic scene
purposes only), overlay_en, overlay_ar, audio, cta, cover. Cover uses the first source URI.

The brief is shared by independent English and Arabic writers. Keep its key message and
CTA concrete. For offers without an offer source, make a travel-planning or visual-comparison
post; never manufacture a discount. A relaxation pillar does not prove a spa. A water-color
pillar does not prove snorkeling or a house reef. Give a specific, image-backed payoff.

Every selected source is a daylight photograph. Do NOT make the story depend on sunrise,
dawn, a morning schedule, sunset, temperature, silence or wind sounds that are not evidenced.
Do not repeat the same water/shore question each day: use the pillar guidance and actual
format (single memorable view, ordered comparison, or continuous scenic experience).
Set cta_kind to save, compare, comment or swipe; brief.cta must mean the same action.
For reel slots, reel_concept MUST be an object with all required fields, never null.
For photo and carousel slots, reel_concept MUST be null. Verify this before returning JSON.

Source fact binding is deterministic: the compiler attaches the facts belonging to each
selected scene. fact_ids may list supplied IDs but the compiler resolves this metadata;
concentrate on the semantic brief, format and ordered scene IDs. Never manufacture a fact.
