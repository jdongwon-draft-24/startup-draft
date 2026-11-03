-- data/76_subscriptions.csv → Supabase subscriptions 표
-- Supabase 대시보드 > SQL Editor 에 통째로 붙여 넣고 Run 하세요.
-- 다시 실행하면 표를 지우고 새로 만들어서, CSV 12줄만 있는 처음 상태로 돌아옵니다.

-- 1. 이미 있던 표와 그 허용 규칙을 모두 지운다
drop table if exists public.subscriptions cascade;

-- 2. 표 만들기 (열 이름은 CSV 머리줄과 같음)
create table public.subscriptions (
  id          bigint generated always as identity primary key,
  name        text    not null,
  category    text    not null,
  monthly_fee integer not null check (monthly_fee >= 0),
  last_used   date    not null
);

-- 3. CSV 데이터 넣기
insert into public.subscriptions (name, category, monthly_fee, last_used) values
  ('영화 · 드라마 구독', '영상',     13500,  '2026-10-18'),
  ('음악 구독',          '음악',     10900,  '2026-10-20'),
  ('클라우드 저장공간',  '업무',     2400,   '2026-10-19'),
  ('헬스장',             '운동',     55000,  '2026-03-02'),
  ('신문 구독',          '읽을거리', 150000, '2026-10-21'),
  ('우유 배달',          '먹거리',   18000,  '2026-10-21'),
  ('정수기 렌털',        '생활',     23900,  '2026-10-21'),
  ('꽃 정기배송',        '생활',     19800,  '2026-09-28'),
  ('전자책 구독',        '읽을거리', 9900,   '2026-08-15'),
  ('반찬 정기배송',      '먹거리',   64000,  '2026-10-16'),
  ('커피 원두 정기배송', '먹거리',   17000,  '2026-10-12'),
  ('문서 작성 도구',     '업무',     8900,   '2026-10-22');

-- 4. 화면(anon 키)에서 표에 접근할 수 있게 열어 주기
grant select, insert, update, delete on public.subscriptions to anon, authenticated;

-- 5. RLS 켜고, 읽기·넣기·고치기·지우기 허용
alter table public.subscriptions enable row level security;

create policy "읽기 허용" on public.subscriptions
  for select to anon, authenticated using (true);

create policy "넣기 허용" on public.subscriptions
  for insert to anon, authenticated with check (true);

create policy "고치기 허용" on public.subscriptions
  for update to anon, authenticated using (true) with check (true);

create policy "지우기 허용" on public.subscriptions
  for delete to anon, authenticated using (true);
