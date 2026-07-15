import type { ApiClient } from '../client';
import type { Example, ExampleCreateInput, ExampleUpdateInput } from '../types';

export class ExamplesResource {
  constructor(private readonly client: ApiClient) {}

  list(): Promise<Example[]> {
    return this.client.get<Example[]>('/examples');
  }

  get(id: string): Promise<Example> {
    return this.client.get<Example>(`/examples/${id}`);
  }

  create(payload: ExampleCreateInput): Promise<Example> {
    return this.client.post<Example>('/examples', payload);
  }

  update(id: string, payload: ExampleUpdateInput): Promise<Example> {
    return this.client.put<Example>(`/examples/${id}`, payload);
  }

  remove(id: string): Promise<null> {
    return this.client.delete<null>(`/examples/${id}`);
  }
}
