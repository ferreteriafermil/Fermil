-- =====================================================================
--  Ferretería Fermil · base de datos en Supabase
--
--  ANTES DE TOCAR "Run": en la línea 14 cambia  tu-correo@ejemplo.com
--  por el correo con el que vas a crear tu acceso de administradora
--  (Authentication → Users → Add user). Solo ese correo podrá subir banners.
--
--  Se puede correr más de una vez sin dañar nada.
--  Al final te muestra los códigos nuevos de los mayoristas.
-- =====================================================================

-- 1. Quién puede administrar la página (subir banners)
create table if not exists public.admins (email text primary key);
insert into public.admins (email) values (lower(trim('tu-correo@ejemplo.com'))) on conflict do nothing;
alter table public.admins enable row level security;

create extension if not exists pgcrypto with schema extensions;

create or replace function public.es_admin() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.admins a where a.email = lower(coalesce(auth.jwt() ->> 'email', '')));
$$;

-- 2. Precios al mayor: los escribe el robot; nadie los lee directo
create table if not exists public.precios_mayor (
  cod text primary key,
  mayor numeric(14,2) not null,
  stock_mayorista numeric(14,2),
  actualizado timestamptz not null default now()
);
alter table public.precios_mayor enable row level security;

-- 3. Mayoristas, con su configuración (qué muestran, descuentos y clientes)
create table if not exists public.mayoristas (
  id text primary key,
  nombre text not null,
  corto text not null,
  prefijo text not null,
  whatsapp text not null,
  codigo text not null unique,
  activo boolean not null default true,
  cfg jsonb not null default '{}'::jsonb,
  actualizado timestamptz not null default now()
);
alter table public.mayoristas enable row level security;

-- Códigos difíciles de adivinar: PREFIJO-XXXX-XXXX, sin letras que se confundan
create or replace function public.fermil_codigo(p_prefijo text) returns text
language plpgsql volatile set search_path = public, extensions as $$
declare
  alfabeto constant text := 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
  b bytea := extensions.gen_random_bytes(8);
  s text := '';
begin
  for i in 0..7 loop
    s := s || substr(alfabeto, (get_byte(b, i) % length(alfabeto)) + 1, 1);
    if i = 3 then s := s || '-'; end if;
  end loop;
  return upper(p_prefijo) || '-' || s;
end $$;

insert into public.mayoristas (id, nombre, corto, prefijo, whatsapp, codigo) values
  ('manuel',   'Manuel Pérez',       'Manuel',   'MANUEL', '584145446979', public.fermil_codigo('MANUEL')),
  ('leonardo', 'Leonardo Rojas',     'Leonardo', 'LEO',    '584245318722', public.fermil_codigo('LEO')),
  ('noel',     'Noel Villavicencio', 'Noel',     'NOEL',   '584127819643', public.fermil_codigo('NOEL'))
on conflict (id) do nothing;

-- 4. Freno contra quien intente adivinar códigos (15 fallos en 15 minutos)
create table if not exists public.intentos (ip text not null, momento timestamptz not null default now());
create index if not exists intentos_ip_momento on public.intentos (ip, momento);
alter table public.intentos enable row level security;

create or replace function public.fermil_ip() returns text
language sql stable as $$
  select coalesce(nullif(trim(split_part(coalesce(current_setting('request.headers', true)::json ->> 'x-forwarded-for', ''), ',', 1)), ''), 'sin-ip');
$$;

create or replace function public.fermil_bloqueado() returns boolean
language sql stable security definer set search_path = public as $$
  select count(*) >= 15 from public.intentos i where i.ip = public.fermil_ip() and i.momento > now() - interval '15 minutes';
$$;

create or replace function public.fermil_fallo() returns void
language sql security definer set search_path = public as $$
  delete from public.intentos where momento < now() - interval '1 day';
  insert into public.intentos (ip) values (public.fermil_ip());
$$;

-- 5. Entrar con un código: devuelve rol, configuración y precios al mayor
create or replace function public.fermil_entrar(p_codigo text) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  c text := upper(trim(coalesce(p_codigo, '')));
  m public.mayoristas%rowtype;
  cl jsonb;
  precios jsonb;
begin
  if public.fermil_bloqueado() then
    raise exception 'Demasiados intentos. Espera 15 minutos.' using errcode = 'P0001';
  end if;
  if length(c) < 6 then perform public.fermil_fallo(); return null; end if;

  select coalesce(jsonb_agg(jsonb_build_array(p.cod, p.mayor, p.stock_mayorista)), '[]'::jsonb)
    into precios from public.precios_mayor p;

  select * into m from public.mayoristas where codigo = c and activo;
  if found then
    return jsonb_build_object('rol', 'mayorista', 'mid', m.id, 'cfg', m.cfg, 'precios', precios);
  end if;

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

-- 6. El mayorista guarda su configuración (solo con su propio código)
create or replace function public.fermil_guardar_cfg(p_codigo text, p_cfg jsonb) returns boolean
language plpgsql security definer set search_path = public as $$
declare c text := upper(trim(coalesce(p_codigo, '')));
begin
  if public.fermil_bloqueado() then return false; end if;
  if p_cfg is null or jsonb_typeof(p_cfg) <> 'object' or length(p_cfg::text) > 400000 then return false; end if;
  update public.mayoristas set cfg = p_cfg, actualizado = now() where codigo = c and activo;
  if not found then perform public.fermil_fallo(); return false; end if;
  return true;
end $$;

revoke all on function public.fermil_entrar(text) from public;
revoke all on function public.fermil_guardar_cfg(text, jsonb) from public;
revoke all on function public.fermil_codigo(text) from public;
revoke all on function public.fermil_fallo() from public;
grant execute on function public.fermil_entrar(text) to anon, authenticated;
grant execute on function public.fermil_guardar_cfg(text, jsonb) to anon, authenticated;

-- 7. Configuración pública de la página (banners): todos leen, solo la administradora cambia
create table if not exists public.config (
  clave text primary key,
  valor jsonb not null default '{}'::jsonb,
  actualizado timestamptz not null default now()
);
alter table public.config enable row level security;
drop policy if exists "config: todos leen" on public.config;
create policy "config: todos leen" on public.config for select to anon, authenticated using (true);
drop policy if exists "config: admin cambia" on public.config;
create policy "config: admin cambia" on public.config for all to authenticated using (public.es_admin()) with check (public.es_admin());
insert into public.config (clave, valor) values ('banners', '{"items": [], "off": []}'::jsonb) on conflict (clave) do nothing;

-- 8. Carpeta pública para las imágenes de los banners
insert into storage.buckets (id, name, public) values ('banners', 'banners', true) on conflict (id) do nothing;
drop policy if exists "banners: admin sube" on storage.objects;
create policy "banners: admin sube" on storage.objects for insert to authenticated with check (bucket_id = 'banners' and public.es_admin());
drop policy if exists "banners: admin cambia" on storage.objects;
create policy "banners: admin cambia" on storage.objects for update to authenticated using (bucket_id = 'banners' and public.es_admin());
drop policy if exists "banners: admin borra" on storage.objects;
create policy "banners: admin borra" on storage.objects for delete to authenticated using (bucket_id = 'banners' and public.es_admin());

-- 9. Códigos de los mayoristas: dáselos a cada uno (no los publiques)
select nombre as mayorista, codigo, whatsapp from public.mayoristas order by nombre;
