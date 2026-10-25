import { useEffect } from 'react';
import { useAuth } from './context/AuthContext.jsx';
import { useHash, guard, navigate, home } from './router.js';
import { LoginPage, RegisterPage } from './pages/Auth.jsx';
import { StudentDashboard, CompanyBrowser, SlotPicker, StudentCalendar, NotificationsPage } from './pages/Student.jsx';
import { InterviewerDashboard, ProfileForm, AvailabilityEditor, ProposalsReview, ResultsEntry, InterviewerCalendar } from './pages/Interviewer.jsx';
import { CoordinatorDashboard, MatchingControl, DraftReview, NoticeBroadcast, CoordinatorCalendar } from './pages/Coordinator.jsx';

const prefix = (role, pages) => Object.fromEntries(Object.entries(pages).map(([k, v]) => [`${role}/${k}`, v]));
const PAGES = {
  login: LoginPage,
  register: RegisterPage,
  ...prefix('student', { dashboard: StudentDashboard, companies: CompanyBrowser, slots: SlotPicker, calendar: StudentCalendar, notifications: NotificationsPage }),
  ...prefix('interviewer', { dashboard: InterviewerDashboard, profile: ProfileForm, availability: AvailabilityEditor, proposals: ProposalsReview, results: ResultsEntry, calendar: InterviewerCalendar, notifications: NotificationsPage }),
  ...prefix('coordinator', { dashboard: CoordinatorDashboard, matching: MatchingControl, draft: DraftReview, notice: NoticeBroadcast, calendar: CoordinatorCalendar, notifications: NotificationsPage }),
};
const keyOf = (p) => { const a = p.split('/').filter(Boolean); return a.length === 1 ? a[0] : a[0] + '/' + a[1]; };

export default function App() {
  const { user } = useAuth();
  const raw = useHash();
  let path = guard(raw, user);
  if (!PAGES[keyOf(path)]) path = user ? home(user.role) : '/login';
  useEffect(() => { if (path !== raw) navigate(path); }, [path, raw]);
  const Page = PAGES[keyOf(path)];
  return <Page param={path.split('/')[3]} />;
}