-- Seed the 8 target cities. Zoning sections + adu_rules are populated by the
-- scraper + extraction pipeline; this only bootstraps the city registry.

insert into cities (name, slug, publisher_type, base_url) values
  ('Los Angeles',  'los_angeles',  'alp',      'https://codelibrary.amlegal.com/codes/los_angeles/latest/lamc/0-0-0-422835'),
  ('San Diego',    'san_diego',    'alp',      'https://codelibrary.amlegal.com/codes/san_diego/latest'),
  ('San Francisco','san_francisco','alp',      'https://codelibrary.amlegal.com/codes/san_francisco/latest/sf_planning/0-0-0-17747'),
  ('Sacramento',   'sacramento',   'alp',      'https://codelibrary.amlegal.com/codes/sacramentoca/latest/sacramento_ca/0-0-0-32996'),
  ('San Jose',     'san_jose',     'municode', 'https://library.municode.com/ca/san_jose/codes/code_of_ordinances'),
  ('Irvine',       'irvine',       'municode', 'https://library.municode.com/ca/irvine/ordinances/code_of_ordinances'),
  ('Long Beach',   'long_beach',   'municode', 'https://library.municode.com/ca/long_beach/codes/municipal_code'),
  ('Oakland',      'oakland',      'municode', 'https://library.municode.com/ca/oakland/codes/planning_code')
on conflict (slug) do update set
  publisher_type = excluded.publisher_type,
  base_url = excluded.base_url;
