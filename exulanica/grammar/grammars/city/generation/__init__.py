"""The city's generators: the code that replaces each stage's ``UnimplementedStage`` with records.

:mod:`~exulanica.grammar.grammars.city.generation.contract` states, before any generator exists,
what the generators consume from every other lane and what they owe it. Nothing here writes a
vertex: every generator emits records in the shapes the city grammar declares, and a tessellator
turns them into geometry.
"""
