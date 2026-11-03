-- =====================================================================
--  Ferretería Fermil · actualización 1 de la base de datos (3 de noviembre de 2026)
--
--  Qué agrega:
--   1. Existencias de los mayoristas por almacén: Almacén Principal (9) y Almacén Unda (17).
--   2. El precio al mayor anterior y la fecha del cambio, para el aviso
--      "Actualización de precios" que ve cada mayorista en su panel.
--
--  Cómo correrlo: Supabase → SQL Editor → New query → pega todo esto → Run.
--  Se puede correr más de una vez sin dañar nada. No cambia los códigos ni los descuentos.
-- =====================================================================

alter table public.precios_mayor add column if not exists stock_principal numeric(14,2);
alter table public.precios_mayor add column if not exists stock_unda numeric(14,2);
alter table public.precios_mayor add column if not exists mayor_anterior numeric(14,2);
alter table public.precios_mayor add column if not exists cambio timestamptz;

-- Entrar con un código. El mayorista recibe el desglose por almacén y los cambios de precio
-- de los últimos 30 días; sus clientes solo reciben el precio y la existencia total.
create or replace function public.fermil_entrar(p_codigo text) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  c text := upper(trim(coalesce(p_codigo, '')));
  m public.mayoristas%rowtype;
  cl jsonb;
  precios jsonb;
  cambios jsonb;
begin
  if public.fermil_bloqueado() then
    raise exception 'Demasiados intentos. Espera 15 minutos.' using errcode = 'P0001';
  end if;
  if length(c) < 6 then perform public.fermil_fallo(); return null; end if;

  select * into m from public.mayoristas where codigo = c and activo;
  if found then
    select coalesce(jsonb_agg(jsonb_build_array(p.cod, p.mayor, p.stock_mayorista, p.stock_principal, p.stock_unda)), '[]'::jsonb)
      into precios from public.precios_mayor p;
    select coalesce(jsonb_agg(jsonb_build_array(p.cod, p.mayor_anterior, p.mayor, p.cambio) order by p.cambio desc), '[]'::jsonb)
      into cambios from public.precios_mayor p
      where p.cambio > now() - interval '30 days' and p.mayor_anterior is not null and p.mayor_anterior <> p.mayor;
    return jsonb_build_object('rol', 'mayorista', 'mid', m.id, 'cfg', m.cfg, 'precios', precios, 'cambios', cambios);
  end if;

  select coalesce(jsonb_agg(jsonb_build_array(p.cod, p.mayor, p.stock_mayorista)), '[]'::jsonb)
    into precios from public.precios_mayor p;

  for m in select * from public.mayoristas where activo loop
    select e into cl from jsonb_array_elements(coalesce(m.cfg -> 'clients', '[]'::jsonb)) e
      where upper(e ->> 'code') = c limit 1;
    if cl is not null then
      return jsonb_build_object(
        'rol', 'cliente', 'mid', m.id, 'ccode', cl ->> 'code', 'cname', cl ->> 'nombre',
        'cfg', jsonb_build_object(
          'hiddenCats', coalesce(m.cfg -> 'hiddenCats', '[]'::jsonb),
          'hiddenProducts', coalesce(m.cfg -> 'hiddenProducts', '[]'::jsonb),
          'noPrice', coalesce(m.cfg -> 'noPrice', '[]'::jsonb),
          'noPriceCats', coalesce(m.cfg -> 'noPriceCats', '[]'::jsonb),
          'disc', coalesce(m.cfg -> 'disc', '{}'::jsonb),
          'clientDisc', jsonb_build_object(cl ->> 'code', coalesce(m.cfg -> 'clientDisc' -> (cl ->> 'code'), '{}'::jsonb)),
          'clients', jsonb_build_array(cl)),
        'precios', precios);
    end if;
  end loop;

  perform public.fermil_fallo();
  return null;
end $$;

revoke all on function public.fermil_entrar(text) from public;
grant execute on function public.fermil_entrar(text) to anon, authenticated;

-- Para revisar: cuántos productos tienen existencia en cada almacén (después de la próxima corrida del robot)
select count(*) filter (where stock_principal > 0) as con_principal,
       count(*) filter (where stock_unda > 0) as con_unda,
       count(*) filter (where cambio is not null) as con_cambio
from public.precios_mayor;
