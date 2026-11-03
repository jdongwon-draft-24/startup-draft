-- Supabase Storage docs 버킷 → 화면(anon 키)에서 문서 올리기 · 목록 보기 허용
-- Supabase 대시보드 > SQL Editor 에 통째로 붙여 넣고 Run 하세요.
-- 여러 번 실행해도 오류가 나지 않습니다. (허용 규칙을 지우고 다시 만듦)

-- 1. docs 버킷이 없으면 만든다 (이미 있으면 그대로 둠)
--    문서는 계약서처럼 남이 보면 안 되는 것이 많아 비공개(public = false)로 만든다
--    비공개 버킷 = 주소만 알아도 아무나 내려받을 수 있는 공개 주소가 생기지 않는 버킷
insert into storage.buckets (id, name, public)
values ('docs', 'docs', false)
on conflict (id) do nothing;

-- 2. 이미 있던 docs 허용 규칙을 지운다
drop policy if exists "docs 목록 보기 허용" on storage.objects;
drop policy if exists "docs 올리기 허용"   on storage.objects;

-- 3. 목록 보기 허용 (docs 버킷 안의 파일만)
create policy "docs 목록 보기 허용" on storage.objects
  for select to anon, authenticated
  using (bucket_id = 'docs');

-- 4. 올리기 허용 (docs 버킷 안으로만)
create policy "docs 올리기 허용" on storage.objects
  for insert to anon, authenticated
  with check (bucket_id = 'docs');

-- 5. 확인: 아래 3줄이 나오면 성공
--    버킷 docs / 허용 SELECT / 허용 INSERT
--    (SQL Editor 는 마지막 결과만 보여 주므로 한 번에 묶어서 조회)
select '버킷' as 종류, name as 이름, case when public then '공개' else '비공개' end as 내용
from storage.buckets
where id = 'docs'
union all
select '허용', policyname, cmd || ' / ' || array_to_string(roles, ', ')
from pg_policies
where schemaname = 'storage'
  and tablename  = 'objects'
  and policyname like 'docs %';
