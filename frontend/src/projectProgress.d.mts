interface ProgressProject {
  id: string; kind: string; busy?: boolean; analysis_confirmed?: boolean;
  images?: {id:string;status:string}[];
  batches?: {job_ids:string[]}[];
  documents?: {brief?: {confirmed_at:string|null}|null;prompts?: {confirmed_at:string|null}|null};
}
export function productionProgress(project: ProgressProject): {total:number;succeeded:number;pending:number;failed:number;unknown:number;complete:boolean};
export function projectDestination(project: ProgressProject): string;
export function projectStatus(project: ProgressProject): {key:string;label:string};
