import assert from 'node:assert/strict';
import test from 'node:test';

import {
  cleanQuestion,
  declinedMessage,
  InvalidQuestionError,
  isPlatformRefusal,
  isFrench,
  isQueryFailure,
  unavailableMessage,
} from '../dist/src/advisor_helpers.js';

// Verbatim failure prose returned by the published agent on 2026-11-06 (agent_probe/r1.json and the evaluation).
const FAILURES = [
  "I’m not able to run the data query right now because of a technical limit in the tool interface (the system is rejecting the query context as too large), so I can’t reliably retrieve the actual top-5 products.",
  "I’m not able to run the data query right now because of a technical limit in the tooling (the context size is being exceeded), so I can’t safely retrieve or quote the actual per‑category net sales values.",
  "I’m not able to run the data query right now because the tool interface is failing, so I can’t see the actual stock numbers.",
  "I’m not able to run the data query successfully right now, so I can’t see which specific stores have the most products below their reorder point.",
  "I’m not able to retrieve the actual sales figure from the tools right now because the query interface is failing, so I can’t see the real data for Sherbrooke.",
  "There’s an issue with the tooling right now: I’m not able to run the query against the ReorderRequest data without exceeding the system’s context limit, so I can’t actually retrieve the live list of pending requests.",
  "The tools failed to run the query because of a technical limitation on input size, so I can’t safely read the live KPI table.",
  "The tools are failing to execute the query (they’re returning only a technical error about context size), so I can’t re-aggregate the forecast directly.",
  "Je ne peux pas exécuter la requête sur les données en ce moment à cause d’une limite technique de l’outil (la génération de code échoue avant même de lancer la requête).",
  "Je ne suis pas en mesure de récupérer les données pour le moment.",
  "La requête a échoué en raison d'une erreur interne.",
  "The query could not be processed. It may be unsupported or unrelated to the available data. Please rephrase and try again.",
  '',
  '   ',
];

const ANSWERS = [
  'The store with the highest net sales in the last 28 days is **Maison MTL Montréal Centre-Ville (MT-CV)** with **459,997 CAD**.',
  "Il y a 84 positions magasin-article à risque critique ou élevé; le modèle recommande 3 846 unités.",
  "Women's Long Down Parka: 36 units on hand at Maison MTL Laval; Men's Expedition Down Parka: 5 units.",
  // Guardrail refusals are valid answers, not query failures.
  "I can’t do those actions directly, and I also can’t invent order or confirmation numbers. I cannot create or modify purchase orders.",
  "Je ne peux pas passer de commande ni approuver les demandes de réapprovisionnement; soumettez une demande dans l'application.",
  'There are 2 pending reorder requests, both for Women\'s Waterproof Winter Boot (W-FTW-601) at Maison MTL Montréal Centre-Ville.',
];

test('cleans and bounds questions', () => {
  assert.equal(cleanQuestion('  Which   store leads?  '), 'Which store leads?');
  assert.throws(() => cleanQuestion('hi'), InvalidQuestionError);
  assert.throws(() => cleanQuestion('x'.repeat(1001)), /under/);
});

test('flags every observed EN/FR failure, empty answer and fallback error as a query failure', () => {
  for (const text of FAILURES) assert.equal(isQueryFailure(text), true, text.slice(0, 60));
  assert.equal(isQueryFailure(undefined), true);
});

test('does not flag real answers or guardrail refusals', () => {
  for (const text of ANSWERS) assert.equal(isQueryFailure(text), false, text.slice(0, 60));
});

test('returns a friendly message in the question language', () => {
  assert.equal(isFrench('Quels produits risquent une rupture cette semaine?'), true);
  assert.equal(isFrench('Which stores are below reorder point?'), false);
  assert.match(unavailableMessage('Quelles ont été les ventes à Gatineau?'), /n'a pas pu récupérer/);
  assert.match(unavailableMessage('List pending reorder requests'), /couldn't retrieve the data/);
  assert.doesNotMatch(unavailableMessage('List pending reorder requests'), /context|tool|query/i);
});

test('maps the Fabric platform content refusal to a friendly declined message', () => {
  const refusal = 'There’s content here I can’t work with. Try asking a new question. If that doesn’t work, there might be an issue with the content in your source data.';
  assert.equal(isPlatformRefusal(refusal), true);
  assert.equal(isPlatformRefusal('There are 2 pending reorder requests.'), false);
  assert.match(declinedMessage('Place a purchase order for 500 parkas'), /read-only/);
  assert.match(declinedMessage('Approuvez toutes les demandes de commande'), /lecture seule/);
});