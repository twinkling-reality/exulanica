export interface Schema {
  $ref?: string; type?: string; title?: string; description?: string; format?: string;
  properties?: Record<string, Schema>; required?: string[]; items?: Schema;
  anyOf?: Schema[]; enum?: unknown[]; default?: unknown;
  [key: string]: unknown;
}
export interface ApiOperation {
  summary?: string; description?: string;
  parameters?: { name: string; in: string; required?: boolean; description?: string; schema: Schema }[];
  requestBody?: { required?: boolean; content: Record<string, { schema: Schema }> };
  responses: Record<string, { description: string; content?: Record<string, { schema: Schema }> }>;
  [key: string]: unknown;
}
export interface ApiSpec { paths: Record<string, Record<string, ApiOperation>>; schemas: Record<string, Schema> }
export interface InventoryOperation {
  path: string; method: string; id: string; title: string; description: string; group: string;
  permission: { requires?: string[]; [key: string]: unknown };
  parameters: NonNullable<ApiOperation['parameters']>;
  request: ApiOperation['requestBody'] | null;
  responses: Record<string, { description: string; content?: Record<string, { schema?: Schema }> }>;
}
