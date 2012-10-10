import colander
from deform.widget import RichTextWidget
from kotti import DBSession
from kotti import get_settings
from kotti.resources import Document
from kotti.resources import Node
from kotti.resources import get_root
from kotti.util import ViewLink
from kotti.util import _
from kotti.util import title_to_name
from kotti.views.form import AddFormView
from kotti.views.form import ContentSchema
from kotti.views.form import EditFormView
from kotti.views.util import ensure_view_selector
from kotti.views.util import nodes_tree
from kotti.workflow import get_workflow
from pyramid.exceptions import Forbidden
from pyramid.httpexceptions import HTTPFound
from pyramid.location import inside
from pyramid.security import has_permission
from pyramid.url import resource_url


class DocumentSchema(ContentSchema):
    body = colander.SchemaNode(
        colander.String(),
        title=_(u'Body'),
        widget=RichTextWidget(theme='advanced', width=790, height=500),
        missing=u"",
        )


def content_type_factories(context, request):
    """Drop down menu for Add button in editor bar.
    """
    all_types = get_settings()['kotti.available_types']
    factories = []
    for factory in all_types:
        if factory.type_info.addable(context, request):
            factories.append(factory)
    return {'factories': factories}


def get_paste_item(context, request):
    items = []
    info = request.session.get('kotti.paste')
    if info:
        ids, action = info
        for id in ids:
            item = DBSession.query(Node).get(id)
            if item is None or not item.type_info.addable(context, request):
                continue
            if action == 'cut' and inside(context, item):
                continue
            if context == item:
                continue
            items.append(item)
    return items


def actions(context, request):
    """Drop down menu for Actions button in editor bar.
    """
    root = get_root()
    actions = [ViewLink('copy', title=_(u'Copy'))]
    is_root = context is root
    if not is_root:
        actions.append(ViewLink('cut', title=_(u'Cut')))
    if get_paste_item(context, request):
        actions.append(ViewLink('paste', title=_(u'Paste')))
    if not is_root:
        actions.append(ViewLink('rename', title=_(u'Rename')))
        actions.append(ViewLink('delete', title=_(u'Delete')))
    if len(context.children) >= 1:
        actions.append(ViewLink('order', title=_(u'Order')))
    return {'actions': [action for action in actions
                        if action.permitted(context, request)]}


def contents_actions(context, request):
    actions = []
    if get_paste_item(context, request):
        actions.append({'name': u'paste', 'title': _(u'Paste'), })
    if context.children:
        actions.append({'name': u'copy', 'title': _(u'Copy'), })
        actions.append({'name': u'cut', 'title': _(u'Cut'), })
        actions.append({'name': u'rename', 'title': _(u'Rename'), })
        actions.append({'name': u'delete', 'title': _(u'Delete'), })
    return actions


def _eval_titles(info):
    result = []
    for d in info:
        d = d.copy()
        d['title'] = eval(d['title']) if 'title' in d else d['name']
        result.append(d)
    return result


def contents(context, request):
    if 'copy' in request.POST:
        return copy_node(context, request)
    if 'cut' in request.POST:
        return cut_node(context, request)
    if 'paste' in request.POST:
        return paste_node(context, request)
    if 'delete' in request.POST:
        location = resource_url(context, request) + '@@delete_nodes'
        request.session['delete-nodes'] = request.POST.getall('children')
        return HTTPFound(location, request=request)
    if 'rename' in request.POST:
        location = resource_url(context, request) + '@@rename_nodes'
        request.session['rename-nodes'] = request.POST.getall('children')
        return HTTPFound(location, request=request)
    return {'actions': contents_actions(context, request)}


def workflow(context, request):
    """Drop down menu for workflow actions.
    """
    wf = get_workflow(context)
    if wf is not None:
        state_info = _eval_titles(wf.state_info(context, request))
        curr_state = [i for i in state_info if i['current']][0]
        trans_info = wf.get_transitions(context, request)
        return {
            'states': dict([(i['name'], i) for i in state_info]),
            'transitions': trans_info,
            'current_state': curr_state,
            }

    return {
        'current_state': None
        }


def workflow_change(context, request):
    """Handle workflow change requests from workflow dropdown
    """
    new_state = request.params['new_state']
    wf = get_workflow(context)
    wf.transition_to_state(context, request, new_state)
    request.session.flash(EditFormView.success_message, 'success')
    return HTTPFound(location=request.resource_url(context))


def copy_node(context, request):
    ids = request.POST.getall('children')
    if not ids:
        ids = [context.id, ]
    request.session['kotti.paste'] = (ids, 'copy')
    for id in ids:
        item = DBSession.query(Node).get(id)
        request.session.flash(_(u'${title} copied.',
                                mapping=dict(title=item.title)), 'success')
    if not request.is_xhr:
        location = resource_url(context, request)
        if request.POST.get('contents', None) is not None:
            location += '@@contents'
        return HTTPFound(location=location)


def cut_node(context, request):
    ids = request.POST.getall('children')
    if not ids:
        ids = [context.id, ]
    request.session['kotti.paste'] = (ids, 'cut')
    for id in ids:
        item = DBSession.query(Node).get(id)
        request.session.flash(_(u'${title} cut.',
                                mapping=dict(title=item.title)), 'success')
    if not request.is_xhr:
        location = resource_url(context, request)
        if request.POST.get('contents', None) is not None:
            location += '@@contents'
        return HTTPFound(location=location)


def paste_node(context, request):
    ids, action = request.session['kotti.paste']
    for count, id in enumerate(ids):
        item = DBSession.query(Node).get(id)
        if item is not None:
            if action == 'cut':
                if not has_permission('edit', item, request):
                    raise Forbidden()
                item.__parent__.children.remove(item)
                context.children.append(item)
                if count is len(ids) - 1:
                    del request.session['kotti.paste']
            elif action == 'copy':
                copy = item.copy()
                name = copy.name
                if not name:  # for root
                    name = copy.title
                name = title_to_name(name, blacklist=context.keys())
                copy.name = name
                context.children.append(copy)
            request.session.flash(_(u'${title} pasted.',
                                    mapping=dict(title=item.title)), 'success')
        else:
            request.session.flash(
                _(u'Could not paste node. It does not exist anymore.'), 'error')
    if not request.is_xhr:
        location = resource_url(context, request)
        if request.POST.get('contents', None) is not None:
            location += '@@contents'
        return HTTPFound(location=location)


def order_node(context, request):
    P = request.POST

    if 'order-up' in P or 'order-down' in P:
        up, down = P.get('order-up'), P.get('order-down')
        child = DBSession.query(Node).get(int(down or up))
        if up is not None:
            mod = -1
        else:  # pragma: no cover
            mod = 1
        index = context.children.index(child)
        context.children.pop(index)
        context.children.insert(index + mod, child)
        request.session.flash(_(u'${title} moved.',
                                mapping=dict(title=child.title)), 'success')
        if not request.is_xhr:
            return HTTPFound(location=request.url)

    elif 'toggle-visibility' in P:
        child = DBSession.query(Node).get(int(P['toggle-visibility']))
        child.in_navigation ^= True
        mapping = dict(title=child.title)
        if child.in_navigation:
            msg = _(u'${title} is now visible in the navigation.',
                    mapping=mapping)
        else:
            msg = _(u'${title} is no longer visible in the navigation.',
                    mapping=mapping)
        request.session.flash(msg, 'success')
        if not request.is_xhr:
            return HTTPFound(location=request.url)

    return {}


def delete_node(context, request):
    if 'delete' in request.POST:
        parent = context.__parent__
        request.session.flash(_(u'${title} deleted.',
                                mapping=dict(title=context.title)), 'success')
        del parent[context.name]
        location = resource_url(parent, request)
        return HTTPFound(location=location)
    return {}


def delete_nodes(context, request):
    if 'delete' in request.POST:
        if 'delete-nodes' in request.session:
            del request.session['delete-nodes']
        ids = request.POST.getall('children-to-delete')
        if not ids:
            request.session.flash(_(u"Nothing deleted."), 'error')
        for id in ids:
            item = DBSession.query(Node).get(id)
            request.session.flash(_(u'${title} deleted.',
                                    mapping=dict(title=item.title)), 'success')
            del context[item.name]
        location = resource_url(context, request) + '@@contents'
        return HTTPFound(location=location)
    ids = items = []
    if 'delete-nodes' in request.session:
        ids = request.session['delete-nodes']
    if ids:
        items = DBSession.query(Node).filter(Node.id.in_(ids)).all()
    return {'multiple': len(items) > 1,
            'items': items}


def rename_node(context, request):
    if 'rename' in request.POST:
        name = request.POST['name']
        title = request.POST['title']
        if not name or not title:
            request.session.flash(_(u'Name and title are required.'), 'error')
        else:
            context.name = name.replace('/', '')
            context.title = title
            request.session.flash(_(u'Item renamed'), 'success')
            location = resource_url(context, request)
            return HTTPFound(location=location)
    return {}


def rename_nodes(context, request):
    if 'rename' in request.POST:
        if 'rename-nodes' in request.session:
            del request.session['rename-nodes']
        ids = request.POST.getall('children-to-rename')
        for id in ids:
            item = DBSession.query(Node).get(id)
            name = request.POST[id + '-name']
            title = request.POST[id + '-title']
            if not name or not title:
                request.session.flash(_(u'Name and title are required.'), 'error')
            else:
                item.name = name.replace('/', '')  # TODO: check if name already exists
                item.title = title
                request.session.flash(_(u'Item renamed.'), 'success')
        location = resource_url(context, request) + '@@contents'
        return HTTPFound(location=location)
    ids = items = []
    if 'rename-nodes' in request.session:
        ids = request.session['rename-nodes']
    if ids:
        items = DBSession.query(Node).filter(Node.id.in_(ids)).all()
    return {'items': items}


# XXX These and the make_generic_edit functions below can probably be
# simplified quite a bit.
def generic_edit(context, request, schema, **kwargs):
    return EditFormView(
        context,
        request,
        schema=schema,
        **kwargs
        )()


def generic_add(context, request, schema, add, title, **kwargs):
    return AddFormView(
        context,
        request,
        schema=schema,
        add=add,
        item_type=title,
        **kwargs
        )()


def make_generic_edit(schema, **kwargs):
    @ensure_view_selector
    def view(context, request):
        return generic_edit(context, request, schema, **kwargs)
    return view


def make_generic_add(schema, add, title=None, **kwargs):
    def view(context, request):
        return generic_add(context, request, schema, add, title, **kwargs)
    return view


def render_tree_navigation(context, request):
    tree = nodes_tree(request)
    return {
        'tree': {
            'children': [tree],
            },
        }


def includeme(config):
    nodes_includeme(config)

    config.add_view(
        make_generic_edit(DocumentSchema()),
        context=Document,
        name='edit',
        permission='edit',
        renderer='kotti:templates/edit/node.pt',
        )

    config.add_view(
        make_generic_add(DocumentSchema(), Document),
        name=Document.type_info.add_view,
        permission='add',
        renderer='kotti:templates/edit/node.pt',
        )

    config.add_view(
        render_tree_navigation,
        name='render_tree_navigation',
        permission='view',
        renderer='kotti:templates/edit/nav-tree.pt',
        )

    config.add_view(
        render_tree_navigation,
        name='navigate',
        permission='view',
        renderer='kotti:templates/edit/nav-tree-view.pt',
        )

    config.add_view(
        content_type_factories,
        name='add-dropdown',
        permission='add',
        renderer='kotti:templates/add-dropdown.pt',
        )

    config.add_view(
        actions,
        name='actions-dropdown',
        permission='view',
        renderer='kotti:templates/actions-dropdown.pt',
        )

    config.add_view(
        workflow_change,
        name='workflow-change',
        permission='state_change',
        )

    config.add_view(
        workflow,
        name='workflow-dropdown',
        permission='edit',
        renderer='kotti:templates/workflow-dropdown.pt',
        )


def nodes_includeme(config):
    config.add_view(
        copy_node,
        name='copy',
        permission='edit',
        )

    config.add_view(
        cut_node,
        name='cut',
        permission='edit',
        )

    config.add_view(
        paste_node,
        name='paste',
        permission='edit',
        )

    config.add_view(
        order_node,
        name='order',
        permission='edit',
        renderer='kotti:templates/edit/order.pt',
        )

    config.add_view(
        delete_node,
        name='delete',
        permission='edit',
        renderer='kotti:templates/edit/delete.pt',
        )

    config.add_view(
        delete_nodes,
        name='delete_nodes',
        permission='edit',
        renderer='kotti:templates/edit/delete-nodes.pt',
        )

    config.add_view(
        rename_node,
        name='rename',
        permission='edit',
        renderer='kotti:templates/edit/rename.pt',
        )

    config.add_view(
        rename_nodes,
        name='rename_nodes',
        permission='edit',
        renderer='kotti:templates/edit/rename-nodes.pt',
        )

    config.scan("kotti.views.edit.default_view_selection")
