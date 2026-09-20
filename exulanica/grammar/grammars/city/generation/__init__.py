"""The city's generators: the code that emits each stage's records.

:mod:`~exulanica.grammar.grammars.city.generation.contract` states what the generators consume
from every other lane and what they owe it. Nothing here writes a vertex: every generator emits
records in the shapes the city grammar declares, and a tessellator turns them into geometry.
"""
