import type { ApiClient } from '../client';
import type { ImportModuleInput, ModuleDetail, ModuleImportJob } from '../types';

/**
 * `/api/v1/modules` 里除「列表」之外的接口——模组详情 + 导入（issue #77 新增）。
 * （`GET /modules` 列表在 RoomsResource.listModules，沿用原有位置不迁移。）
 * 导入是「提交任务 + 轮询状态」两段式，本期后端是 NOT_IMPLEMENTED 桩。
 */
export class ModulesResource {
  constructor(private readonly client: ApiClient) {}

  /** GET /api/v1/modules/{moduleId} — 模组详情 */
  getDetail(moduleId: string): Promise<ModuleDetail> {
    return this.client.get<ModuleDetail>(`/modules/${moduleId}`);
  }

  /** POST /api/v1/modules/import — 提交模组导入任务，返回任务状态 */
  startImport(payload: ImportModuleInput): Promise<ModuleImportJob> {
    return this.client.post<ModuleImportJob>('/modules/import', payload);
  }

  /** GET /api/v1/modules/import/{jobId} — 轮询导入任务状态 */
  getImportJob(jobId: string): Promise<ModuleImportJob> {
    return this.client.get<ModuleImportJob>(`/modules/import/${jobId}`);
  }
}
