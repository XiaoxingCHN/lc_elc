# Run only inside Odoo shell as the service user after backing up the database.
# LC_UI_PROFILE_BACKUP must name a NEW directory writable by the Odoo service user.
# This changes menu/view active flags only. No records are deleted.

import json,hashlib
from pathlib import Path
from lxml import etree
B=Path(__import__('os').environ['LC_UI_PROFILE_BACKUP'])
B.mkdir(parents=True,exist_ok=False)
M=env['ir.ui.menu'].with_context(active_test=False,lang='en_US');V=env['ir.ui.view'].with_context(active_test=False,lang='en_US')
keep_xml=['base.menu_administration','website.menu_website_configuration','lab_inventory.menu_lab_root'];keep=env['ir.ui.menu']
for xmlid in keep_xml:keep|=env.ref(xmlid)
assert len(keep)==3 and not any(keep.mapped('parent_id'))
roots=M.search([('parent_id','=',False)]);hidden=roots-keep
allowed={'general_settings','website'};settings=V.search([('model','=','res.config.settings'),('inherit_id','!=',False),('active','=',True)])
viewrows=[];off=V.browse()
for v in settings:
 arch=etree.fromstring(v.arch_db.encode());introduced=[n.get('name') for n in arch.xpath('.//app[not(@position)]')]
 if introduced and any(n not in allowed for n in introduced):
  assert not any(n in allowed for n in introduced),(v.id,introduced)
  off|=v;viewrows.append({'id':v.id,'name':v.name,'xmlid':v.get_external_id().get(v.id),'apps':introduced,'active':v.active,'arch_sha256':hashlib.sha256(v.arch_db.encode()).hexdigest()})
pos_view=env.ref('point_of_sale.res_config_settings_view_form',raise_if_not_found=False)
if pos_view and pos_view.active:
 assert pos_view in off
snapshot={'keep_xmlids':keep_xml,'menus':[{'id':m.id,'xmlid':m.get_external_id().get(m.id),'name':m.name,'active':m.active} for m in roots],'views':viewrows}
(B/'ui-before.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2))
counts=lambda:{n:env[n].search_count([]) for n in ['product.template','stock.quant','stock.move','lab.catalog.item','lab.bag','lab.issue.line','res.users']}
before=counts()
hidden.write({'active':False});keep.write({'active':True});off.write({'active':False})
form=env['res.config.settings'].get_view(view_type='form');arch=etree.fromstring(form['arch'].encode());apps=[x.get('name') for x in arch.xpath('//app')]
assert set(apps)<=allowed and 'general_settings' in apps and 'website' in apps,apps
assert not arch.xpath('//widget[@name="point_of_sale_test_epos"]')
assert set(M.search([('parent_id','=',False),('active','=',True)]).ids)==set(keep.ids)
after=counts();assert before==after,(before,after)
(B/'settings-after.xml').write_text(form['arch'])
result={'backup':str(B),'kept':[{'id':m.id,'name':m.name} for m in keep],'hidden_menus':len(hidden),'disabled_settings_apps':viewrows,'settings_apps':apps,'business_counts_unchanged':before==after,'counts':after}
(B/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));env.cr.commit();print('RESULT_JSON='+json.dumps(result,ensure_ascii=False))
