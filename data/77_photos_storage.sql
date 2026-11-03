-- Supabase Storage photos 버킷 → 화면(anon 키)에서 그림 올리기 · 목록 보기 허용
-- Supabase 대시보드 > SQL Editor 에 통째로 붙여 넣고 Run 하세요.
-- 여러 번 실행해도 오류가 나지 않습니다. (허용 규칙을 지우고 다시 만듦)

-- 1. photos 버킷이 없으면 만든다 (이미 있으면 그대로 둠)
insert into storage.buckets (id, name, public)
values ('photos', 'photos', true)
on conflict (id) do nothing;

-- 2. 이미 있던 photos 허용 규칙을 지운다
drop policy if exists "photos 목록 보기 허용" on storage.objects;
drop policy if exists "photos 올리기 허용"   on storage.objects;

-- 3. 목록 보기 허용 (photos 버킷 안의 파일만)
create policy "photos 목록 보기 허용" on storage.objects
  for select to anon, authenticated
  using (bucket_id = 'photos');

-- 4. 올리기 허용 (photos 버킷 안으로만)
create policy "photos 올리기 허용" on storage.objects
  for insert to anon, authenticated
  with check (bucket_id = 'photos');

-- 5. 확인: 아래 3줄이 나오면 성공
--    버킷 photos / 허용 SELECT / 허용 INSERT
--    (SQL Editor 는 마지막 결과만 보여 주므로 한 번에 묶어서 조회)
select '버킷' as 종류, name as 이름, case when public then '공개' else '비공개' end as 내용
from storage.buckets
where id = 'photos'
union all
select '허용', policyname, cmd || ' / ' || array_to_string(roles, ', ')
from pg_policies
where schemaname = 'storage'
  and tablename  = 'objects'
  and policyname like 'photos %';
