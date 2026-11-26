import type { Project } from './creationProjectApi';
export default function TeamSourceNotice({project}:{project:Project}){
  if(!project.team_source)return null;
  return <p className="feedback">此项目复制自团队共享「{project.team_source.title}」第 {project.team_source.version} 版，后续修改保存在自己的工作区。<a href={'#/team?share='+project.team_source.id}>查看来源</a></p>;
}
