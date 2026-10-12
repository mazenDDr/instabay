# Evidence-first brief — FR-04, FR-06

Produce ONE JSON INSTANCE, not a schema. Do not repeat $defs, properties, required or types.
Return brief, media_ids, fact_ids, observations, pillar_intent, sequence_reason and cta_kind.

The candidate photographs are attached as images, in the same order as `scenes`; each image is
preceded by its scene id. LOOK at them. They are the only evidence of what this place has.
evidence.property_name is the resort; evidence.geography is where it is. If
evidence.reference_only is true the photos are a historical reference of the named property:
never present them as Insta Bay's own facilities. Otherwise they are the owner's own resort.

Read post_format first. This request is for ONE post, not the entire week.
Photo: media_ids has EXACTLY ONE scene; give one vivid, specific thought drawn from it.
Carousel: choose 2–5 DIFFERENT photographs ordered as a mini exploration or a useful
comparison, and explain the progression in sequence_reason.
Reel: choose 3–5 DIFFERENT scenes that together give a readable sense of the place (water,
pools, buildings, palms, terraces). Each scene gets gentle motion for about five seconds.
Never pick two photos of the same spot from nearly the same viewpoint in one post.

Keep the slot's pillar and format and read evidence.pillar_guidance for that pillar. Give the
post a distinct, concrete angle and one useful viewer action; previous_angles are already used.

observations: for EVERY selected scene whose `has_facts` is false,
add {"media_id", "en", "ar"}: one short factual sentence in English and the same sentence in
Modern Standard Arabic stating only what is clearly visible in that photo (objects, layout,
light, time of day only if obvious). No names, prices, services or facilities you cannot see.
Scenes that already list facts need no observation.

Never invent a facility, room interior, underwater view, species, price, deal, availability or
guest testimonial. A relaxation pillar does not prove a spa; water colour does not prove
snorkeling. For offers without an offer source, make a travel-planning or comparison post.

media_ids must be exact scene IDs. brief.photo_uri and fact_ids are filled in by the compiler;
any value is fine. All brief fields are strings except must_not and reel_concept.
reel_concept is null for photo/carousel. For a reel it MUST be an object with hook, shots
(semantic scene purposes only), overlay_en, overlay_ar, audio, cta, cover.
Set cta_kind to save, compare, comment or swipe; brief.cta must mean the same action.
