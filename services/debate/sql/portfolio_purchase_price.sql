-- Entra 관리자로 psql-whatif-dev의 실제 애플리케이션 DB에 연결한 뒤 실행.
-- 기존 행과 API의 amount_krw 의미(저장 시점 평가금액)는 유지합니다.
ALTER TABLE public.user_holding
  ADD COLUMN IF NOT EXISTS avg_purchase_price_krw numeric
  CHECK (avg_purchase_price_krw > 0);

-- 검증: avg_purchase_price_krw 행이 하나 반환되어야 합니다.
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'user_holding'
  AND column_name = 'avg_purchase_price_krw';
