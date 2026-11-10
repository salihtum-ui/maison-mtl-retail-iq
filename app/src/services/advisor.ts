import { getRayfinClient } from './rayfinClient';

export interface AdvisorAnswer {
  status: 'answered' | 'unavailable' | 'invalid' | 'declined';
  answer: string;
  message: string;
  agentName: string;
  ontologyName: string;
  generatedAt: string;
  attempts: number;
  readOnly: true;
}

export async function askMtlAdvisor(question: string): Promise<AdvisorAnswer> {
  return getRayfinClient().functions.askMtlAdvisor.invoke({ questionInput: question }, { timeoutMs: 245_000 });
}
