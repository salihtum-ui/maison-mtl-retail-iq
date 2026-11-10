import {
  AudienceType,
  type RayfinContext,
  UserDataFunctions,
} from '@microsoft/fabric-user-data-functions';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

import type { MtlAppSchema } from '../../data/schema.js';
import {
  cleanQuestion,
  declinedMessage,
  InvalidQuestionError,
  isPlatformRefusal,
  isQueryFailure,
  unavailableMessage,
} from './advisor_helpers.js';
import { AGENT_ID, AGENT_NAME, AGENT_TOOL_NAME, ONTOLOGY_NAME, WORKSPACE_ID } from './fabric_config.js';

const udf = new UserDataFunctions();

const AGENT_URL = new URL(
  `https://api.fabric.microsoft.com/v1/mcp/workspaces/${WORKSPACE_ID}/dataagents/${AGENT_ID}/agent`,
);
const ATTEMPTS = 2;
const ATTEMPT_TIMEOUT_MS = 105_000;
const PLACEHOLDER_ID = '00000000-0000-0000-0000-000000000000';
const CONFIGURED = WORKSPACE_ID !== PLACEHOLDER_ID && AGENT_ID !== PLACEHOLDER_ID;

export type AdvisorStatus = 'answered' | 'unavailable' | 'invalid' | 'declined';

export type AdvisorAnswer = {
  status: AdvisorStatus;
  answer: string;
  message: string;
  agentName: string;
  ontologyName: string;
  generatedAt: string;
  attempts: number;
  readOnly: true;
};

function answerText(content: unknown): string {
  if (!Array.isArray(content)) return '';
  return content
    .map(item => {
      if (!item || typeof item !== 'object' || !('type' in item) || !('text' in item)) return '';
      return item.type === 'text' && typeof item.text === 'string' ? item.text.trim() : '';
    })
    .filter(Boolean)
    .join('\n\n');
}

/** One published Data Agent call. Returns '' on any MCP, transport, timeout or empty-answer failure. */
async function askAgent(question: string, token: string): Promise<string> {
  const client = new Client({ name: 'mtl-retail-iq', version: '1.1.0' }, { capabilities: {} });
  const transport = new StreamableHTTPClientTransport(AGENT_URL, {
    requestInit: { headers: { Authorization: `Bearer ${token}` } },
    reconnectionOptions: {
      initialReconnectionDelay: 500,
      maxReconnectionDelay: 2_000,
      reconnectionDelayGrowFactor: 1.5,
      maxRetries: 2,
    },
  });
  try {
    await client.connect(transport);
    const tools = await client.listTools();
    if (tools.tools.filter(tool => tool.name === AGENT_TOOL_NAME).length !== 1) {
      console.error(`Expected MCP tool ${AGENT_TOOL_NAME} is not advertised.`);
      return '';
    }
    const result = await client.callTool(
      { name: AGENT_TOOL_NAME, arguments: { userQuestion: question } },
      undefined,
      { timeout: ATTEMPT_TIMEOUT_MS },
    );
    if (result.isError) {
      console.error('Data Agent tool returned an error result.');
      return '';
    }
    return answerText(result.content);
  } catch (error) {
    console.error('Data Agent call failed', error instanceof Error ? error.message : error);
    return '';
  } finally {
    await client.close().catch(() => undefined);
  }
}

function result(status: AdvisorStatus, answer: string, message: string, attempts: number): AdvisorAnswer {
  return {
    status,
    answer,
    message,
    agentName: AGENT_NAME,
    ontologyName: ONTOLOGY_NAME,
    generatedAt: new Date().toISOString(),
    attempts,
    readOnly: true,
  };
}

udf.func(
  'askMtlAdvisor',
  async (questionInput: string, ctx: RayfinContext<MtlAppSchema, AudienceType.Fabric>): Promise<AdvisorAnswer> => {
    let question: string;
    try {
      question = cleanQuestion(questionInput);
    } catch (error) {
      if (error instanceof InvalidQuestionError) return result('invalid', '', error.message, 0);
      throw error;
    }
    if (!CONFIGURED) {
      return result('unavailable', '', 'The advisor is not configured yet: run `python deploy.py app` to connect it to the '
        + 'deployed Data Agent.', 0);
    }
    for (let attempt = 1; attempt <= ATTEMPTS; attempt++) {
      const answer = await askAgent(question, ctx.Tokens.Fabric);
      if (isPlatformRefusal(answer)) return result('declined', '', declinedMessage(question), attempt);
      if (!isQueryFailure(answer)) return result('answered', answer, '', attempt);
      console.warn(`Data Agent attempt ${attempt} did not return data.`);
    }
    // Never return the agent's failure prose, and never substitute an unverified source (e.g. a fallback "0").
    return result('unavailable', '', unavailableMessage(question), ATTEMPTS);
  },
  [],
);
