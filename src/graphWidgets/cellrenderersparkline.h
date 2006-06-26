/* eggcellrenderersparkline.h
 * Copyright (C) 2005  Red Hat, Inc.,  David Malcolm <dmalcolm@redhat.com>
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Library General Public
 * License as published by the Free Software Foundation; either
 * version 2 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Library General Public License for more details.
 *
 * You should have received a copy of the GNU Library General Public
 * License along with this library; if not, write to the
 * Free Software Foundation, Inc., 59 Temple Place - Suite 330,
 * Boston, MA 02111-1307, USA.
 */

#ifndef __GTK_CELL_RENDERER_SPARKLINE_H__
#define __GTK_CELL_RENDERER_SPARKLINE_H__

#include <pango/pango.h>
#include <gtk/gtkcellrenderer.h>


G_BEGIN_DECLS


#define GTK_TYPE_CELL_RENDERER_SPARKLINE		(gtk_cell_renderer_sparkline_get_type ())
#define GTK_CELL_RENDERER_SPARKLINE(obj)		(G_TYPE_CHECK_INSTANCE_CAST ((obj), GTK_TYPE_CELL_RENDERER_SPARKLINE, GtkCellRendererSparkline))
#define GTK_CELL_RENDERER_SPARKLINE_CLASS(klass)	(G_TYPE_CHECK_CLASS_CAST ((klass), GTK_TYPE_CELL_RENDERER_SPARKLINE, GtkCellRendererSparklineClass))
#define GTK_IS_CELL_RENDERER_SPARKLINE(obj)		(G_TYPE_CHECK_INSTANCE_TYPE ((obj), GTK_TYPE_CELL_RENDERER_SPARKLINE))
#define GTK_IS_CELL_RENDERER_SPARKLINE_CLASS(klass)	(G_TYPE_CHECK_CLASS_TYPE ((klass), GTK_TYPE_CELL_RENDERER_SPARKLINE))
#define GTK_CELL_RENDERER_SPARKLINE_GET_CLASS(obj)   (G_TYPE_INSTANCE_GET_CLASS ((obj), GTK_TYPE_CELL_RENDERER_SPARKLINE, GtkCellRendererSparklineClass))

typedef struct _GtkCellRendererSparkline      GtkCellRendererSparkline;
typedef struct _GtkCellRendererSparklineClass GtkCellRendererSparklineClass;

struct _GtkCellRendererSparkline
{
  GtkCellRenderer parent;

  /*< private >*/
};

struct _GtkCellRendererSparklineClass
{
  GtkCellRendererClass parent_class;

  /* Padding for future expansion */
  void (*_gtk_reserved1) (void);
  void (*_gtk_reserved2) (void);
  void (*_gtk_reserved3) (void);
  void (*_gtk_reserved4) (void);
};

GType            gtk_cell_renderer_sparkline_get_type (void) G_GNUC_CONST;
GtkCellRenderer *gtk_cell_renderer_sparkline_new      (void);

G_END_DECLS


#endif /* __GTK_CELL_RENDERER_SPARKLINE_H__ */
