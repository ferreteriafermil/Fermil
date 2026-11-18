-- =====================================================================
--  Ferretería Fermil · actualización 3 de la base de datos (18 de noviembre de 2026)
--
--  Qué agrega: la CALCULADORA DE VIAJES PARA LOS MAYORISTAS.
--  Cada mayorista (Leo, Nohel, Manuel) arma su viaje solo con los pueblos de SU ruta y con
--  los productos por código. El cálculo se hace aquí, en la base de datos, para que nunca
--  vean costos, nómina, km ni fletes: solo si el viaje se aprueba y qué le falta
--  (venta o carga) o cuánto se pasa de peso. Usa los mismos datos del panel de tabulaciones.
--
--  Cómo correrlo: Supabase → SQL Editor → New query → pega todo esto → Run.
--  Se puede correr más de una vez. No cambia nada de lo que ya existe.
-- =====================================================================

-- 1. Qué vendedor del tabulador es cada mayorista (se puede cambiar desde el panel de tabulaciones)
update public.tabulador
   set datos = jsonb_set(datos, '{vendedor_de}', '{"manuel": "Manuel", "leonardo": "Leo", "noel": "Nohel"}'::jsonb)
 where id = 1 and not (datos ? 'vendedor_de');

-- 2. Cálculo del viaje para un mayorista
create or replace function public.fermil_viaje_vendedor(p_codigo text, p_paradas jsonb default '[]'::jsonb,
                                                        p_vehiculo text default null, p_tasa numeric default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  c text := upper(trim(coalesce(p_codigo, '')));
  m public.mayoristas%rowtype;
  d jsonb; p jsonb; vend text;
  mis jsonb;            -- pueblos de la ruta del vendedor
  vehs jsonb;           -- lista de camiones (sin costos)
  paradas jsonb := '[]'::jsonb;
  par jsonb; it jsonb; items jsonb;
  lug jsonb; nombre text;
  venta numeric := 0; peso numeric := 0; pv numeric; pp numeric; mayor numeric; kg numeric; cant numeric;
  ruta text[]; i int; a int; b int; km_tot numeric := 0; km numeric; np int := 0; dias int;
  topo numeric := 0; n_peajes numeric := 0; tasa numeric;
  v jsonb; costo_km numeric; peaje numeric; nomina numeric; viat numeric; total numeric; tope numeric; vmin numeric;
  ocup numeric; estado text; evals jsonb := '[]'::jsonb; ev jsonb; elegido jsonb; recomendado text;
  prom_liv numeric; prom_pes numeric; sin_peso int := 0; existe boolean;
begin
  if public.fermil_bloqueado() then return null; end if;
  select * into m from public.mayoristas where codigo = c and activo;
  if not found then perform public.fermil_fallo(); return null; end if;

  select datos into d from public.tabulador where id = 1;
  if d is null or d = '{}'::jsonb then return jsonb_build_object('error', 'El tabulador todavía no tiene datos'); end if;
  p := d->'parametros';
  vend := coalesce(d->'vendedor_de'->>m.id, m.corto);

  -- ordenados por distancia desde el origen
  select coalesce(jsonb_agg(x order by km_o), '[]'::jsonb) into mis from (
    select l->>'nombre' as x,
           (d->'matriz'->(select o2 - 1 from jsonb_array_elements(d->'lugares') with ordinality t2(l2, o2) where l2->>'nombre' = p->>'origen')::int->>(o::int - 1))::numeric as km_o
      from jsonb_array_elements(d->'lugares') with ordinality as t(l, o)
     where l->>'vendedor' = vend) s;

  select coalesce(jsonb_agg(jsonb_build_object('modelo', f->>'modelo', 'tamano', f->>'tamano', 'capacidad', (f->>'capacidad')::numeric)), '[]'::jsonb)
    into vehs from jsonb_array_elements(d->'flota') f;

  if p_paradas is null or jsonb_typeof(p_paradas) <> 'array' or jsonb_array_length(p_paradas) = 0 then
    return jsonb_build_object('vendedor', vend, 'lugares', mis, 'vehiculos', vehs);
  end if;

  -- Paradas: solo pueblos de su ruta; venta y peso salen de los productos (precio al mayor y peso de PLADE)
  for par in select * from jsonb_array_elements(p_paradas) limit 15 loop
    nombre := par->>'lugar';
    if nombre is null or not (mis ? nombre) then continue; end if;
    pv := 0; pp := 0; items := '[]'::jsonb;
    for it in select * from jsonb_array_elements(coalesce(par->'items', '[]'::jsonb)) limit 200 loop
      cant := greatest(0, coalesce((it->>'cant')::numeric, 0));
      select pm.mayor, pm.peso, true into mayor, kg, existe from public.precios_mayor pm where pm.cod = upper(it->>'cod');
      if not found then mayor := 0; kg := null; existe := false; end if;
      kg := coalesce(nullif(kg, 0), nullif((d->'pesos_manual'->>upper(it->>'cod'))::numeric, 0));
      if kg is null and cant > 0 then sin_peso := sin_peso + 1; end if;
      pv := pv + coalesce(mayor, 0) * cant; pp := pp + coalesce(kg, 0) * cant;
      items := items || jsonb_build_object('cod', upper(it->>'cod'), 'cant', cant, 'mayor', mayor, 'peso', kg, 'existe', existe);
    end loop;
    if jsonb_array_length(items) = 0 then
      pv := greatest(0, coalesce((par->>'venta')::numeric, 0)); pp := greatest(0, coalesce((par->>'peso')::numeric, 0));
    end if;
    venta := venta + pv; peso := peso + pp; np := np + 1;
    paradas := paradas || jsonb_build_object('lugar', nombre, 'venta', round(pv, 2), 'peso', round(pp, 2), 'items', items);
  end loop;
  if np = 0 then
    return jsonb_build_object('vendedor', vend, 'lugares', mis, 'vehiculos', vehs, 'paradas', paradas);
  end if;

  -- Km del viaje: origen → paradas → origen (con la matriz del tabulador)
  ruta := array[p->>'origen'] || array(select x->>'lugar' from jsonb_array_elements(paradas) x) || array[p->>'origen'];
  for i in 2 .. array_length(ruta, 1) loop
    select o - 1 into a from jsonb_array_elements(d->'lugares') with ordinality t(l, o) where l->>'nombre' = ruta[i - 1];
    select o - 1 into b from jsonb_array_elements(d->'lugares') with ordinality t(l, o) where l->>'nombre' = ruta[i];
    km := (d->'matriz'->a->>b)::numeric;
    km_tot := km_tot + coalesce(km, 0);
  end loop;
  km_tot := greatest((p->>'km_min')::numeric, km_tot);
  dias := greatest(case when np >= (p->>'paradas_2dias')::numeric then 2 else 1 end, ceil(km_tot / nullif((p->>'km_dia')::numeric, 0))::int);

  -- Topografía (el pueblo más exigente) y peajes (por corredor, el pueblo con más peajes; ida y vuelta)
  select max((l->>'topo')::numeric) into topo from jsonb_array_elements(d->'lugares') l
   where l->>'nombre' in (select x->>'lugar' from jsonb_array_elements(paradas) x);
  select coalesce(sum(mx), 0) * 2 into n_peajes from (
    select max((l->>'peajes')::numeric) as mx from jsonb_array_elements(d->'lugares') l
     where l->>'nombre' in (select x->>'lugar' from jsonb_array_elements(paradas) x)
     group by l->>'corredor') s;

  tasa := case when coalesce((p->>'bcv_auto')::boolean, true) and coalesce(p_tasa, 0) > 0 then p_tasa else (p->>'bcv')::numeric end;
  select avg(((ch->>'mensual')::numeric + (ch->>'bonos')::numeric + (ch->>'parafiscales')::numeric + (ch->>'prestaciones')::numeric) / 30)
    into prom_liv from jsonb_array_elements(d->'choferes') ch where ch->>'tipo' = 'Liviano';
  select avg((ch->>'por_viaje')::numeric) into prom_pes from jsonb_array_elements(d->'choferes') ch where ch->>'tipo' = 'Pesado';

  -- Cada camión (mismo cálculo del Excel y del panel, con el chofer promedio de su tipo)
  for v in select * from jsonb_array_elements(d->'flota') loop
    costo_km := ((v->>'n_cauchos')::numeric * (v->>'precio_caucho')::numeric / nullif((v->>'vida_cauchos')::numeric, 0)
               + (v->>'precio_paila')::numeric / nullif((v->>'litros_paila')::numeric, 0)
                 * ((v->>'litros_motor')::numeric + (p->>'litros_extra')::numeric) / nullif((p->>'km_cambio_aceite')::numeric, 0)
               + (p->>'gasoil')::numeric / nullif((v->>'rend')::numeric, 0))
               * (1 + (v->>'mant')::numeric) * coalesce(nullif((v->>'factor')::numeric, 0), 1);
    peaje := coalesce((d->'peajes'->>(v->>'cat_peaje'))::numeric, 0) / nullif(tasa, 0);
    if v->>'tipo' = 'Gandola' then
      nomina := coalesce(prom_pes, 0) + (p->>'diario_pesado')::numeric * dias;
      viat := (p->>'viatico_gandola')::numeric * dias;
    else
      nomina := coalesce(prom_liv, 0) * dias;
      viat := (p->>'viatico_camion')::numeric * dias;
    end if;
    total := (km_tot * costo_km * (1 + coalesce(topo, 0)) + np * (p->>'costo_parada')::numeric
              + n_peajes * coalesce(peaje, 0) + nomina + viat + (p->>'hospedaje')::numeric * greatest(0, dias - 1))
             * (1 + (p->>'utilidad')::numeric);
    tope := coalesce(nullif((p->>case v->>'tamano' when 'PEQUEÑO' then 'tope_pequeno' when 'MEDIANO' then 'tope_mediano' else 'tope_grande' end)::numeric, 0), 0.03);
    vmin := total / tope;
    ocup := peso / nullif((v->>'capacidad')::numeric, 0);
    estado := case when ocup > 1 then 'exceso' when ocup < (p->>'ocupacion_min')::numeric then 'vacio' when venta < vmin then 'flete' else 'ok' end;
    evals := evals || jsonb_build_object('modelo', v->>'modelo', 'tamano', v->>'tamano', 'capacidad', (v->>'capacidad')::numeric,
                                         'total', total, 'vmin', vmin, 'ocup', ocup, 'estado', estado);
  end loop;

  -- Recomendado: el aprobado más barato; si ninguno aprueba, el más barato donde cabe la carga; si no cabe en ninguno, el más grande
  select e->>'modelo' into recomendado from jsonb_array_elements(evals) e
   order by (e->>'estado' = 'ok') desc, ((e->>'ocup')::numeric <= 1) desc,
            case when (e->>'ocup')::numeric <= 1 then (e->>'total')::numeric else -(e->>'capacidad')::numeric end
   limit 1;
  select e into elegido from jsonb_array_elements(evals) e where e->>'modelo' = coalesce(p_vehiculo, recomendado);
  if elegido is null then select e into elegido from jsonb_array_elements(evals) e where e->>'modelo' = recomendado; end if;

  return jsonb_build_object(
    'vendedor', vend, 'lugares', mis, 'paradas', paradas, 'venta', round(venta, 2), 'peso', round(peso, 2), 'sin_peso', sin_peso,
    'recomendado', recomendado, 'vehiculo', elegido->>'modelo', 'tamano', elegido->>'tamano', 'capacidad', (elegido->>'capacidad')::numeric,
    'ocupacion', round((elegido->>'ocup')::numeric, 4), 'estado', elegido->>'estado', 'ocupacion_min', (p->>'ocupacion_min')::numeric,
    'falta_venta', case when elegido->>'estado' = 'flete' then ceil((elegido->>'vmin')::numeric - venta) else 0 end,
    'falta_kg', round(greatest(0, (p->>'ocupacion_min')::numeric * (elegido->>'capacidad')::numeric - peso)),
    'exceso_kg', round(greatest(0, peso - (elegido->>'capacidad')::numeric)),
    'vehiculos', (select jsonb_agg(jsonb_build_object('modelo', e->>'modelo', 'tamano', e->>'tamano', 'capacidad', (e->>'capacidad')::numeric, 'estado', e->>'estado')) from jsonb_array_elements(evals) e));
end $$;

revoke all on function public.fermil_viaje_vendedor(text, jsonb, text, numeric) from public;
grant execute on function public.fermil_viaje_vendedor(text, jsonb, text, numeric) to anon, authenticated;
