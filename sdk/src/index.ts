import { ApiClient, type ApiClientOptions } from './client';
import { ExamplesResource } from './resources/examples';

export * from './types';
export { ApiClient, ApiError } from './client';
export type { ApiClientOptions } from './client';

export class TrpgSdk {
  readonly examples: ExamplesResource;

  constructor(options: ApiClientOptions) {
    const client = new ApiClient(options);
    this.examples = new ExamplesResource(client);
  }
}

export function createTrpgSdk(options: ApiClientOptions): TrpgSdk {
  return new TrpgSdk(options);
}
