export interface ResumeRole {
  id: string;
  title: string;
  company: string;
  startDate: string;
  endDate: string;
  bullets: string[];
}

export interface ResumeData {
  summary: string;
  roles: ResumeRole[];
  skills: string[];
}
