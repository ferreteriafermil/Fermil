-- =====================================================================
--  Ferretería Fermil · actualización 2 de la base de datos (17 de noviembre de 2026)
--
--  Qué agrega:
--   1. El peso (kg) de cada producto, que el robot trae de la ficha de PLADE.
--   2. El panel administrativo de TABULACIONES: un código aparte (no es de mayorista)
--      para calcular fletes, rutas y ventas mínimas desde la página.
--   3. Los datos del tabulador (parámetros, flota, choferes, lugares y la matriz de km),
--      privados: solo los ve quien entra con el código de administración.
--
--  Cómo correrlo: Supabase → SQL Editor → New query → pega todo esto → Run.
--  Se puede correr más de una vez sin dañar nada. No cambia los códigos de los mayoristas.
--  Al final te muestra el código de administración: dáselo solo a quien maneje las tabulaciones.
-- =====================================================================

-- 1. Peso de cada producto
alter table public.precios_mayor add column if not exists peso numeric(12,4);

-- 2. Quién puede entrar al panel de tabulaciones
create table if not exists public.tabulador_admins (
  id text primary key,
  nombre text not null,
  codigo text not null unique,
  activo boolean not null default true
);
alter table public.tabulador_admins enable row level security;
insert into public.tabulador_admins (id, nombre, codigo)
values ('administracion', 'Administración Fermil', public.fermil_codigo('ADMIN'))
on conflict (id) do nothing;

-- 3. Datos del tabulador (una sola fila). Nadie los lee directo: solo por las funciones de abajo
create table if not exists public.tabulador (
  id int primary key default 1 check (id = 1),
  datos jsonb not null,
  actualizado timestamptz not null default now()
);
alter table public.tabulador enable row level security;
-- Los datos iniciales (costos, flota, nómina y km) NO van en este repositorio público:
-- se cargan con el archivo privado supabase-actualizacion-2-CON-DATOS.sql que tiene la administración.
insert into public.tabulador (id, datos) values (1, '{}'::jsonb)
on conflict (id) do nothing;

-- 4. Entrar con un código (mayorista, cliente o administración de tabulaciones)
create or replace function public.fermil_entrar(p_codigo text) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  c text := upper(trim(coalesce(p_codigo, '')));
  m public.mayoristas%rowtype;
  a public.tabulador_admins%rowtype;
  cl jsonb;
  precios jsonb;
  cambios jsonb;
begin
  if public.fermil_bloqueado() then
    raise exception 'Demasiados intentos. Espera 15 minutos.' using errcode = 'P0001';
  end if;
  if length(c) < 6 then perform public.fermil_fallo(); return null; end if;

  -- Panel administrativo de tabulaciones: datos del tabulador y precio al mayor + peso de cada producto
  select * into a from public.tabulador_admins where codigo = c and activo;
  if found then
    select coalesce(jsonb_agg(jsonb_build_array(p.cod, p.mayor, p.stock_mayorista, p.peso)), '[]'::jsonb)
      into precios from public.precios_mayor p;
    return (select jsonb_build_object('rol', 'tabulador', 'nombre', a.nombre, 'datos', t.datos, 'actualizado', t.actualizado, 'precios', precios)
              from public.tabulador t where t.id = 1);
  end if;

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

-- 5. Guardar los cambios del tabulador (solo con el código de administración)
create or replace function public.fermil_guardar_tabulador(p_codigo text, p_datos jsonb) returns timestamptz
language plpgsql security definer set search_path = public as $$
declare
  c text := upper(trim(coalesce(p_codigo, '')));
  t timestamptz;
begin
  if public.fermil_bloqueado() then return null; end if;
  if not exists (select 1 from public.tabulador_admins where codigo = c and activo) then
    perform public.fermil_fallo();
    return null;
  end if;
  if p_datos is null or jsonb_typeof(p_datos) <> 'object' or length(p_datos::text) > 2000000 then return null; end if;
  update public.tabulador set datos = p_datos, actualizado = now() where id = 1 returning actualizado into t;
  return t;
end $$;
revoke all on function public.fermil_guardar_tabulador(text, jsonb) from public;
grant execute on function public.fermil_guardar_tabulador(text, jsonb) to anon, authenticated;

-- 6. Tu código de administración (no lo publiques)
select nombre, codigo from public.tabulador_admins;
