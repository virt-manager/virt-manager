/* eggcellrenderersparkline.c
 * Copyright (C) 2005-2006 Red Hat, Inc.,  David Malcolm <dmalcolm@redhat.com>
 * Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
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

#include <stdlib.h>
#include "cellrenderersparkline.h"

static void gtk_cell_renderer_sparkline_init(GtkCellRendererSparkline *cellsparkline);
static void gtk_cell_renderer_sparkline_class_init(GtkCellRendererSparklineClass *class);
static void gtk_cell_renderer_sparkline_finalize(GObject *object);

static void gtk_cell_renderer_sparkline_get_property(GObject *object,
						     guint param_id,
						     GValue *value,
						     GParamSpec *pspec);
static void gtk_cell_renderer_sparkline_set_property(GObject *object,
						     guint param_id,
						     const GValue *value,
						     GParamSpec *pspec);
static void gtk_cell_renderer_sparkline_get_size(GtkCellRenderer *cell,
						 GtkWidget *widget,
						 GdkRectangle *cell_area,
						 gint *x_offset,
						 gint *y_offset,
						 gint *width,
						 gint *height);
static void gtk_cell_renderer_sparkline_render(GtkCellRenderer *cell,
					       GdkWindow *window,
					       GtkWidget *widget,
					       GdkRectangle *background_area,
					       GdkRectangle *cell_area,
					       GdkRectangle *expose_area,
					       GtkCellRendererState flags);

enum {
  EDITED,
  LAST_SIGNAL
};

enum {
  PROP_0,
  PROP_NUMDATAPOINTS,
  PROP_DATAARRAY
};

static gpointer parent_class;
static guint sparkline_cell_renderer_signals [LAST_SIGNAL];

#define GTK_CELL_RENDERER_SPARKLINE_GET_PRIVATE(obj) (G_TYPE_INSTANCE_GET_PRIVATE ((obj), GTK_TYPE_CELL_RENDERER_SPARKLINE, GtkCellRendererSparklinePrivate))

typedef struct _GtkCellRendererSparklinePrivate GtkCellRendererSparklinePrivate;
struct _GtkCellRendererSparklinePrivate
{
  gboolean filled;
  GValueArray *data_array;
};


GType gtk_cell_renderer_sparkline_get_type (void)
{
  static GType cell_sparkline_type = 0;

  if (!cell_sparkline_type) {
    static const GTypeInfo cell_sparkline_info = {
      sizeof (GtkCellRendererSparklineClass),
      NULL,		/* base_init */
      NULL,		/* base_finalize */
      (GClassInitFunc) gtk_cell_renderer_sparkline_class_init,
      NULL,		/* class_finalize */
      NULL,		/* class_data */
      sizeof (GtkCellRendererSparkline),
      0,              /* n_preallocs */
      (GInstanceInitFunc) gtk_cell_renderer_sparkline_init,
    };

    cell_sparkline_type =
      g_type_register_static (GTK_TYPE_CELL_RENDERER, "GtkCellRendererSparkline",
			      &cell_sparkline_info, 0);
  }

  return cell_sparkline_type;
}

static void gtk_cell_renderer_sparkline_init (GtkCellRendererSparkline *cellsparkline)
{
  GtkCellRendererSparklinePrivate *priv;

  priv = GTK_CELL_RENDERER_SPARKLINE_GET_PRIVATE (cellsparkline);

  priv->filled = TRUE;
  //    priv->filled = FALSE;
  priv->data_array = g_value_array_new(0);
}

static void gtk_cell_renderer_sparkline_class_init (GtkCellRendererSparklineClass *class)
{
  GObjectClass *object_class = G_OBJECT_CLASS (class);
  GtkCellRendererClass *cell_class = GTK_CELL_RENDERER_CLASS (class);

  parent_class = g_type_class_peek_parent (class);

  object_class->finalize = gtk_cell_renderer_sparkline_finalize;

  object_class->get_property = gtk_cell_renderer_sparkline_get_property;
  object_class->set_property = gtk_cell_renderer_sparkline_set_property;

  cell_class->get_size = gtk_cell_renderer_sparkline_get_size;
  cell_class->render = gtk_cell_renderer_sparkline_render;

  g_object_class_install_property (object_class,
				   PROP_DATAARRAY,
				   g_param_spec_value_array ("data_array",
							     "Data array",
							     "GValueArray of data",
							     g_param_spec_double("data_array_value",
										 "Data array value",
										 "GValueArray element",
										 0.0,
										 100.0,
										 0,
										 G_PARAM_READABLE | G_PARAM_WRITABLE),
							     G_PARAM_READABLE | G_PARAM_WRITABLE));

  g_type_class_add_private (object_class, sizeof (GtkCellRendererSparklinePrivate));
}

static void gtk_cell_renderer_sparkline_finalize (GObject *object)
{
  GtkCellRendererSparklinePrivate *priv;

  priv = GTK_CELL_RENDERER_SPARKLINE_GET_PRIVATE (object);


  (* G_OBJECT_CLASS (parent_class)->finalize) (object);
}

static void gtk_cell_renderer_sparkline_get_property (GObject *object,
						      guint param_id,
						      GValue *value,
						      GParamSpec *pspec)
{
  GtkCellRendererSparklinePrivate *priv;

  priv = GTK_CELL_RENDERER_SPARKLINE_GET_PRIVATE (object);

  switch (param_id)
    {
    case PROP_DATAARRAY:
      g_value_set_boxed(value, priv->data_array);
      break;

    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, param_id, pspec);
      break;
    }
}

static void
gtk_cell_renderer_sparkline_set_property (GObject      *object,
					  guint         param_id,
					  const GValue *value,
					  GParamSpec   *pspec)
{
  GtkCellRendererSparklinePrivate *priv;

  priv = GTK_CELL_RENDERER_SPARKLINE_GET_PRIVATE (object);

  switch (param_id)
    {
    case PROP_DATAARRAY:
      g_value_array_free(priv->data_array);
      priv->data_array = g_value_array_copy(g_value_get_boxed(value));
      break;

    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, param_id, pspec);
      break;
    }
}

static void gtk_cell_renderer_sparkline_get_size (GtkCellRenderer *cell,
						  GtkWidget *widget,
						  GdkRectangle *cell_area,
						  gint *x_offset,
						  gint *y_offset,
						  gint *width,
						  gint *height)
{
  GtkCellRendererSparklinePrivate *priv;
  GValueArray *data;

  priv = GTK_CELL_RENDERER_SPARKLINE_GET_PRIVATE (cell);

  data = priv->data_array;

  if (width)
    *width = data->n_values;

  if (height)
    *height = 20;

  if (cell_area) {
    if (x_offset) {
      *x_offset = 0;
    }
    if (y_offset) {
      *y_offset = 0;
    }
  }
}

static double get_y (GdkRectangle *cell_area,
		     GValueArray *data,
		     int index)
{
  double baseline_y = cell_area->y + cell_area->height;
  GValue *val = g_value_array_get_nth(data, index);
  return baseline_y - (cell_area->height * g_value_get_double(val));
}

static void
gtk_cell_renderer_sparkline_render (GtkCellRenderer *cell,
				    GdkDrawable *window,
				    GtkWidget *widget,
				    GdkRectangle *background_area,
				    GdkRectangle *cell_area,
				    GdkRectangle *expose_area,
				    GtkCellRendererState flags)
{
  GtkCellRendererSparklinePrivate *priv;
  GValueArray *data;
  GdkPoint *points;
  int index;
  double pixels_per_point;
#if USE_CAIRO
  cairo_t *cr;
#endif

  priv = GTK_CELL_RENDERER_SPARKLINE_GET_PRIVATE(cell);

  data = priv->data_array;

  pixels_per_point = (double)cell_area->width / ((double)data->n_values-1);

  points = g_new(GdkPoint, data->n_values);
  for (index=0;index<data->n_values;index++) {
    double cx = ((double)index * pixels_per_point);
    double cy = get_y (cell_area, data, index);
    
    points[index].x = cx + cell_area->x;
    points[index].y = cy;
  }


#if USE_CAIRO
  cr = gdk_cairo_create (GDK_DRAWABLE(window));

  /* Clip to the cell: */
  cairo_save (cr);
  cairo_rectangle (cr, cell_area->x, cell_area->y, cell_area->width, cell_area->height);
  cairo_clip (cr);

  /* Render the line: */
  cairo_set_line_width (cr, (double)0.5);

#if 0
  cairo_move_to(cr, cell_area->x, cell_area->y);
  cairo_line_to(cr, cell_area->x, cell_area->y + cell_area->height);
  cairo_line_to(cr, cell_area->x + cell_area->width, cell_area->y + cell_area->height);
  cairo_line_to(cr, cell_area->x + cell_area->width, cell_area->y);
  cairo_line_to(cr, cell_area->x, cell_area->y);
  cairo_stroke(cr);
#endif

  for (index=0;index<data->n_values;index++) {
    double cx = points[index].x;
    double cy = points[index].y;
    if (index) {
      cairo_line_to (cr, cx, cy);
    } else {
      cairo_move_to (cr, cx, cy);
    }
  }
  if (data->n_values) {
    if (priv->filled) {
      double baseline_y = cell_area->height + cell_area->y;
      cairo_line_to (cr, points[data->n_values-1].x, baseline_y);
      cairo_line_to (cr, 0, baseline_y);
      cairo_fill (cr);
    } else {
      cairo_stroke (cr);
    }
  }
  /* Stop clipping: */
  cairo_restore (cr);

  cairo_destroy (cr);
#else
  gdk_draw_lines(GDK_DRAWABLE(window),
		 widget->style->fg_gc[GTK_WIDGET_STATE(widget)],
		 points, data->n_values);
#endif

  g_free(points);

}

#define __GTK_CELL_RENDERER_SPARKLINE_C__
