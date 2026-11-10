const FAILURE_PATTERNS = [
  // English: the agent explaining that its own query or tooling failed
  /(?:not able|unable|can(?:not|'t|’t))\s+(?:to\s+)?(?:run|execute|retrieve|complete|process|query)\b[^.\n]{0,100}\b(?:query|queries|data|request|tool|numbers|figures|values|results)/i,
  /\bcontext (?:size|limit|length|window)\b/i,
  /\btool(?:s|ing)?(?: interface)? (?:is |are |was |were )?(?:failing|failed|unavailable|not working)/i,
  /\btechnical (?:limit(?:ation)?|error|issue|problem)\b/i,
  /\b(?:the )?query could not be processed\b/i,
  /\bcode generation fail/i,
  /\binternal (?:context|execution|query)?\s*(?:size )?error\b/i,
  /\bmaximum context (?:length|size)\b/i,
  // French
  /\bje ne (?:peux|suis) pas (?:en mesure (?:de |d['’]))?\s*(?:ex[ée]cuter|r[ée]cup[ée]rer|interroger|lancer|acc[ée]der|obtenir)\b/i,
  /\blimite technique\b/i,
  /\b(?:la )?requ[êe]te (?:a [ée]chou[ée]|n['’]a pas pu|ne peut pas|ne peut [eê]tre)/i,
  /\b(?:l['’]outil|les outils)\b[^.\n]{0,40}\b(?:[ée]choue|ne fonctionne|indisponible)/i,
  /\btaille (?:du|de) (?:contexte)\b/i,
  /\bg[ée]n[ée]ration (?:de|du) (?:la )?code\b[^.\n]{0,30}[ée]choue/i,
];

export const MAX_QUESTION_LENGTH = 1_000;

export class InvalidQuestionError extends Error {}

export function cleanQuestion(value: string): string {
  const question = String(value ?? '').trim().replace(/\s+/g, ' ');
  if (question.length < 3) throw new InvalidQuestionError('Enter a question of at least 3 characters.');
  if (question.length > MAX_QUESTION_LENGTH) {
    throw new InvalidQuestionError(`Keep the question under ${MAX_QUESTION_LENGTH.toLocaleString('en-CA')} characters.`);
  }
  return question;
}

/** True when the agent's text is an explanation that it could not query the data (never show it as an answer). */
export function isQueryFailure(answer: string | null | undefined): boolean {
  const text = String(answer ?? '').trim();
  if (text.length < 2) return true;
  return FAILURE_PATTERNS.some(pattern => pattern.test(text));
}

export function isFrench(question: string): boolean {
  return /[àâçéèêëîïôûùüÿœ]/i.test(question) ||
    /\b(?:quels?|quelles?|combien|magasin|ventes|semaine|derniers?|produits?|rupture|commande)\b/i.test(question);
}

export function unavailableMessage(question: string): string {
  return isFrench(question)
    ? "MTL IQ n'a pas pu récupérer les données pour cette question. Réessayez dans un instant ou précisez-la (un magasin, une catégorie ou une période)."
    : "MTL IQ couldn't retrieve the data for this question. Try again in a moment, or narrow it to one store, category or period.";
}

/** Fabric's platform-level content refusal (e.g. for order/approval instructions); not a data answer. */
export function isPlatformRefusal(answer: string | null | undefined): boolean {
  return /there['’]s content here i can['’]t work with/i.test(String(answer ?? ''));
}

export function declinedMessage(question: string): string {
  return isFrench(question)
    ? "MTL IQ ne peut pas traiter cette demande. L'assistant est en lecture seule : pour commander, soumettez une demande de réapprovisionnement dans l'application (approbation par un acheteur)."
    : "MTL IQ can't help with that request. It is read-only: to reorder, submit a reorder request in the app for buyer approval.";
}
