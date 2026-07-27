"""Loop C — News Intelligence (Phase 4.1 Del B).

Nyhedsdrevet shadow-trading: henter headlines, lader LLM'en forudsige prisretning
(shadow signals), evaluerer dem mod faktisk prisbevægelse og måler præcision over tid.
Rører ALDRIG kapital — det er ren måling af, om news-signaler ville have haft merværdi.
Confirmation-hooket i engine'en er Phase 5-arbejde (config-flag default false).
"""
